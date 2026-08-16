"""
Tests the Google Sheets CSV parsing/normalization logic in data_store.py,
and that it's actually used when the *_SHEET_CSV_URL env vars are set
(via a monkeypatched fetch — no real network call). Also confirms the
local JSON fallback still works when those env vars are unset (covered
more thoroughly in test_tools.py, which never sets them).

Run with: pytest tests/test_data_store_sheets.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.tools import data_store


def test_parse_items_single():
    items = data_store._parse_items("Atomic Habits by James Clear x1 @21.00")
    assert items == [{"title": "Atomic Habits", "author": "James Clear", "qty": 1, "price": 21.00}]


def test_parse_items_multiple():
    items = data_store._parse_items(
        "The Midnight Library by Matt Haig x1 @19.99; Project Hail Mary by Andy Weir x1 @22.50"
    )
    assert len(items) == 2
    assert items[0]["title"] == "The Midnight Library"
    assert items[1]["author"] == "Andy Weir"
    assert items[1]["price"] == 22.50


def test_parse_items_empty():
    assert data_store._parse_items("") == []
    assert data_store._parse_items("   ") == []


def test_parse_items_skips_malformed_chunk():
    # Second chunk is missing the "x{qty}" part — should be skipped, not raise.
    items = data_store._parse_items("Good Book by Some Author x1 @9.99; totally broken chunk")
    assert len(items) == 1
    assert items[0]["title"] == "Good Book"


def test_normalize_order_row_delivered():
    row = {
        "order_id": "BK-10021",
        "customer_email": "jane.doe@example.com",
        "customer_name": "Jane Doe",
        "order_date": "2026-08-05",
        "status": "Delivered",
        "shipped_date": "",
        "delivered_date": "2026-08-09",
        "estimated_delivery": "",
        "items": "The Midnight Library by Matt Haig x1 @19.99",
        "shipping_method": "Standard (3-5 business days)",
        "tracking_number": "AUPOST-88213741",
        "carrier": "Australia Post",
        "total": "19.99",
        "return_window_days": "30",
        "cancellation_reason": "",
    }
    order = data_store._normalize_order_row(row)
    assert order["order_id"] == "BK-10021"
    assert order["status"] == "delivered"  # lowercased
    assert order["delivered_date"] == "2026-08-09"
    assert "shipped_date" not in order  # blank optional fields are omitted, not empty-stringed
    assert order["total"] == 19.99
    assert order["return_window_days"] == 30
    assert order["items"][0]["title"] == "The Midnight Library"


def test_normalize_return_row():
    row = {
        "return_id": "RT-5001",
        "order_id": "BK-10018",
        "item_title": "Educated",
        "status": "Completed",
        "requested_date": "2026-07-10",
        "resolved_date": "2026-07-14",
        "resolution": "refunded",
        "refund_amount": "20.00",
    }
    r = data_store._normalize_return_row(row)
    assert r["status"] == "completed"
    assert r["refund_amount"] == 20.00


def test_normalize_customer_row():
    row = {"email": "Jane.Doe@example.com ", "name": "Jane Doe", "account_created": "2024-03-11"}
    c = data_store._normalize_customer_row(row)
    assert c["email"] == "Jane.Doe@example.com"
    assert c["name"] == "Jane Doe"


def test_sheet_mode_used_when_env_vars_set(monkeypatch):
    """When ORDERS_SHEET_CSV_URL is set, get_order_by_id should use the
    (stubbed) sheet fetch instead of the local JSON file."""
    fake_rows = [
        {
            "order_id": "SHEET-001",
            "customer_email": "sheettest@example.com",
            "customer_name": "Sheet Test",
            "order_date": "2026-08-01",
            "status": "delivered",
            "shipped_date": "",
            "delivered_date": "2026-08-03",
            "estimated_delivery": "",
            "items": "Test Book by Test Author x1 @10.00",
            "shipping_method": "Standard",
            "tracking_number": "",
            "carrier": "",
            "total": "10.00",
            "return_window_days": "30",
            "cancellation_reason": "",
        }
    ]

    def fake_fetch_csv_rows(url):
        assert url == "https://example.com/fake-orders.csv"
        return fake_rows

    monkeypatch.setenv("ORDERS_SHEET_CSV_URL", "https://example.com/fake-orders.csv")
    monkeypatch.setattr(data_store, "_fetch_csv_rows", fake_fetch_csv_rows)
    data_store._cache.clear()  # avoid stale cache from a previous test run

    order = data_store.get_order_by_id("SHEET-001")
    assert order is not None
    assert order["customer_email"] == "sheettest@example.com"

    # Local-only order should NOT be found while in sheet mode (a real
    # sheet is the sole source of truth once configured, same as switching
    # a real backend).
    assert data_store.get_order_by_id("BK-10021") is None


def test_falls_back_to_local_json_when_env_vars_unset(monkeypatch):
    monkeypatch.delenv("ORDERS_SHEET_CSV_URL", raising=False)
    order = data_store.get_order_by_id("BK-10021")
    assert order is not None
    assert order["customer_email"] == "jane.doe@example.com"


def test_get_all_orders_returns_every_order_most_recent_first(monkeypatch):
    monkeypatch.delenv("ORDERS_SHEET_CSV_URL", raising=False)
    orders = data_store.get_all_orders()
    assert len(orders) == 5
    order_ids = {o["order_id"] for o in orders}
    assert order_ids == {"BK-10021", "BK-10022", "BK-10023", "BK-10018", "BK-10024"}
    # Most recent order_date first
    dates = [o.get("order_date") or "" for o in orders]
    assert dates == sorted(dates, reverse=True)
