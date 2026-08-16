"""
Loads the mock order/customer data. This is the ONE place that knows about
the JSON files — swap this module's internals for real API/DB calls when
integrating with a real order management system, and everything in
order_tools.py / returns_tools.py keeps working unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_DATA_DIR = Path(__file__).resolve().parent.parent / "mock_data"


def _load_orders_file() -> dict:
    with open(_DATA_DIR / "orders.json") as f:
        return json.load(f)


def get_order_by_id(order_id: str) -> Optional[dict]:
    data = _load_orders_file()
    for order in data["orders"]:
        if order["order_id"].lower() == order_id.strip().lower():
            return order
    return None


def get_orders_by_email(email: str) -> list[dict]:
    data = _load_orders_file()
    email = email.strip().lower()
    return [o for o in data["orders"] if o["customer_email"].lower() == email]


def get_past_returns_for_order(order_id: str) -> list[dict]:
    data = _load_orders_file()
    return [r for r in data.get("returns", []) if r["order_id"].lower() == order_id.strip().lower()]


def customer_email_exists(email: str) -> bool:
    with open(_DATA_DIR / "customers.json") as f:
        data = json.load(f)
    email = email.strip().lower()
    return any(c["email"].lower() == email for c in data["customers"])
