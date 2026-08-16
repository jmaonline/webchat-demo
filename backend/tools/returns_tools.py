"""
Return/refund tools.

IMPORTANT: `submit_return_request` NEVER executes a refund. It only ever
creates a pending entry in the human approval queue (approval_queue.py).
This boundary must be preserved even when swapping in real backend systems.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import data_store
from .. import approval_queue


def check_return_eligibility(order_id: str, customer_email: str) -> dict:
    """
    Determine whether an order is eligible for return/refund under policy
    (delivered, within the return window, not already returned/cancelled).

    Args:
        order_id: The bookstore order ID.
        customer_email: The email on the order (identity check).

    Returns:
        dict describing eligibility (eligible: bool), the reason, and
        relevant order details the agent can relay to the customer.
    """
    order = data_store.get_order_by_id(order_id)
    if order is None:
        return {"error": "not_found", "message": f"No order found with ID {order_id}."}

    if order["customer_email"].strip().lower() != customer_email.strip().lower():
        return {
            "error": "email_mismatch",
            "message": "The email provided doesn't match our records for this order.",
        }

    if order["status"] == "cancelled":
        return {"eligible": False, "reason": "Order was cancelled and never delivered — nothing to return."}

    if order["status"] in ("processing", "shipped"):
        return {
            "eligible": False,
            "reason": (
                f"Order is currently '{order['status']}' and hasn't been delivered yet. "
                "It can be cancelled instead if it hasn't shipped, or returned once it arrives."
            ),
        }

    if order["status"] != "delivered":
        return {"eligible": False, "reason": f"Order status '{order['status']}' is not eligible for return."}

    past_returns = data_store.get_past_returns_for_order(order_id)
    if any(r["status"] in ("completed", "pending") for r in past_returns):
        return {
            "eligible": False,
            "reason": "A return has already been requested or completed for this order.",
            "existing_return": past_returns[0],
        }

    delivered_date = datetime.fromisoformat(order["delivered_date"])
    window_days = order.get("return_window_days", 30)
    deadline = delivered_date + timedelta(days=window_days)
    days_remaining = (deadline - datetime.now()).days

    if days_remaining < 0:
        return {
            "eligible": False,
            "reason": (
                f"The {window_days}-day return window closed on "
                f"{deadline.date().isoformat()}."
            ),
        }

    return {
        "eligible": True,
        "reason": f"Delivered {order['delivered_date']}; {days_remaining} day(s) left in the {window_days}-day return window.",
        "order_total": order["total"],
        "items": order["items"],
    }


def submit_return_request(
    order_id: str,
    customer_email: str,
    item_title: str,
    reason: str,
) -> dict:
    """
    Submit a return/refund request for HUMAN REVIEW. This does not process
    a refund — it queues the request for a support staff member to
    approve or deny. Only call this after check_return_eligibility has
    confirmed the order is eligible and the customer has confirmed they
    want to proceed.

    Args:
        order_id: The bookstore order ID.
        customer_email: The email on the order.
        item_title: Which item the customer wants to return (or "all items").
        reason: The customer's stated reason for the return.

    Returns:
        dict with the created request_id and status "pending", or an error.
    """
    order = data_store.get_order_by_id(order_id)
    if order is None:
        return {"error": "not_found", "message": f"No order found with ID {order_id}."}

    if order["customer_email"].strip().lower() != customer_email.strip().lower():
        return {
            "error": "email_mismatch",
            "message": "The email provided doesn't match our records for this order.",
        }

    if item_title.strip().lower() == "all items":
        refund_amount = order["total"]
    else:
        matches = [i for i in order["items"] if i["title"].strip().lower() == item_title.strip().lower()]
        refund_amount = sum(i["price"] * i["qty"] for i in matches) if matches else order["total"]

    request = approval_queue.create_return_refund_request(
        order_id=order_id,
        customer_email=customer_email,
        item_title=item_title,
        reason=reason,
        requested_refund_amount=round(refund_amount, 2),
    )
    return {
        "request_id": request["request_id"],
        "status": request["status"],
        "message": (
            f"Return request {request['request_id']} submitted for review. "
            "Our team typically reviews these within 1 business day."
        ),
    }
