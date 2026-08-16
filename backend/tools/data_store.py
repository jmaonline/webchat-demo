"""
Loads order/customer/return data.

Primary source (when configured): published Google Sheets CSV exports, via
the env vars ORDERS_SHEET_CSV_URL / CUSTOMERS_SHEET_CSV_URL /
RETURNS_SHEET_CSV_URL. See docs/GOOGLE_SHEETS_SETUP.md for how to set one
up. Falls back to the local mock_data/*.json files when those env vars
aren't set, so tests and local dev work offline with zero setup.

Swap point for a REAL order system later: replace the bodies of
get_order_by_id / get_orders_by_email / get_past_returns_for_order /
customer_email_exists with real API/DB calls. Everything in
order_tools.py / returns_tools.py / account_tools.py keeps working
unchanged either way, since they only call these four functions.
"""
from __future__ import annotations

import csv
import io
import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Optional

_DATA_DIR = Path(__file__).resolve().parent.parent / "mock_data"

# Simple in-memory cache so a burst of chat messages doesn't hit Google for
# every single tool call. 30s is plenty fresh for a support agent while
# keeping the sheet feeling "live" to whoever's editing it for testing.
_CACHE_TTL_SECONDS = 30
_cache: dict[str, tuple[float, list[dict]]] = {}


def _fetch_csv_rows(url: str) -> list[dict]:
    with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310 - fixed https URL from env config
        text = resp.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def _cached_csv_rows(cache_key: str, url: str) -> list[dict]:
    now = time.time()
    cached = _cache.get(cache_key)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]
    rows = _fetch_csv_rows(url)
    _cache[cache_key] = (now, rows)
    return rows


def _parse_items(items_str: str) -> list[dict]:
    """
    Parse the sheet's compact item format: 'Title by Author xQTY @PRICE',
    multiple items separated by ';'. Skips any chunk that doesn't match
    rather than raising, so one typo'd row in the sheet doesn't take the
    whole agent down.
    """
    items: list[dict] = []
    if not items_str or not items_str.strip():
        return items
    for chunk in items_str.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            main, price_part = chunk.rsplit("@", 1)
            main, qty_part = main.rsplit(" x", 1)
            title, author = main.split(" by ", 1)
            items.append(
                {
                    "title": title.strip(),
                    "author": author.strip(),
                    "qty": int(qty_part.strip()),
                    "price": float(price_part.strip()),
                }
            )
        except ValueError:
            continue
    return items


def _normalize_order_row(row: dict) -> dict:
    order = {
        "order_id": (row.get("order_id") or "").strip(),
        "customer_email": (row.get("customer_email") or "").strip(),
        "customer_name": (row.get("customer_name") or "").strip(),
        "order_date": row.get("order_date") or None,
        "status": (row.get("status") or "").strip().lower(),
        "items": _parse_items(row.get("items", "")),
        "shipping_method": row.get("shipping_method") or None,
        "tracking_number": row.get("tracking_number") or None,
        "carrier": row.get("carrier") or None,
        "total": float(row["total"]) if row.get("total") else 0.0,
        "return_window_days": int(row["return_window_days"]) if row.get("return_window_days") else 30,
    }
    # Only set date fields that are actually present, matching the shape
    # the tools already expect (e.g. "delivered_date" only exists once an
    # order has actually been delivered).
    for optional_field in ("shipped_date", "delivered_date", "estimated_delivery", "cancellation_reason"):
        if row.get(optional_field):
            order[optional_field] = row[optional_field]
    return order


def _normalize_return_row(row: dict) -> dict:
    return {
        "return_id": (row.get("return_id") or "").strip(),
        "order_id": (row.get("order_id") or "").strip(),
        "item_title": (row.get("item_title") or "").strip(),
        "status": (row.get("status") or "").strip().lower(),
        "requested_date": row.get("requested_date") or None,
        "resolved_date": row.get("resolved_date") or None,
        "resolution": row.get("resolution") or None,
        "refund_amount": float(row["refund_amount"]) if row.get("refund_amount") else 0.0,
    }


def _normalize_customer_row(row: dict) -> dict:
    return {
        "email": (row.get("email") or "").strip(),
        "name": (row.get("name") or "").strip(),
        "account_created": row.get("account_created") or None,
    }


def _load_orders() -> list[dict]:
    url = os.environ.get("ORDERS_SHEET_CSV_URL")
    if url:
        return [_normalize_order_row(r) for r in _cached_csv_rows("orders", url)]
    with open(_DATA_DIR / "orders.json") as f:
        return json.load(f)["orders"]


def _load_returns() -> list[dict]:
    url = os.environ.get("RETURNS_SHEET_CSV_URL")
    if url:
        return [_normalize_return_row(r) for r in _cached_csv_rows("returns", url)]
    with open(_DATA_DIR / "orders.json") as f:
        return json.load(f).get("returns", [])


def _load_customers() -> list[dict]:
    url = os.environ.get("CUSTOMERS_SHEET_CSV_URL")
    if url:
        return [_normalize_customer_row(r) for r in _cached_csv_rows("customers", url)]
    with open(_DATA_DIR / "customers.json") as f:
        return json.load(f)["customers"]


def get_order_by_id(order_id: str) -> Optional[dict]:
    for order in _load_orders():
        if order["order_id"].lower() == order_id.strip().lower():
            return order
    return None


def get_orders_by_email(email: str) -> list[dict]:
    email = email.strip().lower()
    return [o for o in _load_orders() if o["customer_email"].lower() == email]


def get_past_returns_for_order(order_id: str) -> list[dict]:
    return [r for r in _load_returns() if r["order_id"].lower() == order_id.strip().lower()]


def customer_email_exists(email: str) -> bool:
    email = email.strip().lower()
    return any(c["email"].lower() == email for c in _load_customers())
