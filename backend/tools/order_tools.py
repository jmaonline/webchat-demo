"""
Order lookup tools. Read-only. Requires order_id + customer_email to match
(a minimal identity check for this prototype — see ARCHITECTURE.md §6 for
why a real deployment should prefer authenticated sessions instead).
"""
from __future__ import annotations

from . import data_store


def get_order_status(order_id: str, customer_email: str) -> dict:
    """
    Look up a single order's status, items, and tracking info.

    Args:
        order_id: The bookstore order ID, e.g. "BK-10021".
        customer_email: The email address on the order, used to verify the
            requester is entitled to see these details.

    Returns:
        dict with either the order details, or an "error" key explaining
        why the lookup failed (not found / email mismatch) — the agent
        should relay a helpful message in either case, never raw errors.
    """
    order = data_store.get_order_by_id(order_id)
    if order is None:
        return {"error": "not_found", "message": f"No order found with ID {order_id}."}

    if order["customer_email"].strip().lower() != customer_email.strip().lower():
        return {
            "error": "email_mismatch",
            "message": (
                "The email provided doesn't match our records for this order. "
                "Please double-check the order ID and email used at checkout."
            ),
        }

    return {"order": order}


def find_orders_by_email(customer_email: str) -> dict:
    """
    List recent orders for a customer, for when they don't have the order
    number on hand. Only returns orders — never other customers' data.

    Args:
        customer_email: The email address to look up orders for.

    Returns:
        dict with a list of matching orders (may be empty).
    """
    orders = data_store.get_orders_by_email(customer_email)
    return {"orders": orders, "count": len(orders)}
