"""
Human-in-the-loop approval queue for actions the agent is not allowed to
execute directly (refunds / returns).

The agent can only ever *create* a pending request here. Only a human,
via the admin endpoints in app.py, can approve or deny it. This module is
intentionally the single choke point where money-moving actions happen, so
it's easy to audit and easy to swap for a real ticketing system
(Zendesk/Jira/internal admin tool) later.

Storage is in-memory for this prototype. Swap `_QUEUE` for a real DB table
in production (and this module's functions become thin wrappers around
DB queries instead of list operations).
"""
from __future__ import annotations

import itertools
import threading
from datetime import datetime, timezone
from typing import Literal, Optional, TypedDict

_lock = threading.Lock()
_id_counter = itertools.count(5100)  # arbitrary starting id, distinct from mock RT-5001


class ApprovalRequest(TypedDict):
    request_id: str
    type: Literal["return_refund"]
    order_id: str
    customer_email: str
    item_title: Optional[str]
    reason: str
    requested_refund_amount: float
    status: Literal["pending", "approved", "denied"]
    created_at: str
    resolved_at: Optional[str]
    resolved_by: Optional[str]
    resolution_notes: Optional[str]


_QUEUE: dict[str, ApprovalRequest] = {}


def create_return_refund_request(
    *,
    order_id: str,
    customer_email: str,
    item_title: Optional[str],
    reason: str,
    requested_refund_amount: float,
) -> ApprovalRequest:
    """Create a new pending return/refund request. Never auto-approved."""
    with _lock:
        request_id = f"RT-{next(_id_counter)}"
        req: ApprovalRequest = {
            "request_id": request_id,
            "type": "return_refund",
            "order_id": order_id,
            "customer_email": customer_email,
            "item_title": item_title,
            "reason": reason,
            "requested_refund_amount": requested_refund_amount,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "resolved_at": None,
            "resolved_by": None,
            "resolution_notes": None,
        }
        _QUEUE[request_id] = req
        return req


def get_request(request_id: str) -> Optional[ApprovalRequest]:
    return _QUEUE.get(request_id)


def list_requests(status: Optional[str] = None) -> list[ApprovalRequest]:
    values = list(_QUEUE.values())
    if status:
        values = [r for r in values if r["status"] == status]
    return sorted(values, key=lambda r: r["created_at"])


def resolve_request(
    request_id: str, *, approve: bool, resolved_by: str, notes: str = ""
) -> Optional[ApprovalRequest]:
    """Human staff action: approve or deny a pending request."""
    with _lock:
        req = _QUEUE.get(request_id)
        if req is None:
            return None
        if req["status"] != "pending":
            return req  # already resolved; idempotent no-op
        req["status"] = "approved" if approve else "denied"
        req["resolved_at"] = datetime.now(timezone.utc).isoformat()
        req["resolved_by"] = resolved_by
        req["resolution_notes"] = notes
        # NOTE: In a real system, "approved" would now trigger the actual
        # refund call to the payment processor (Stripe/PayPal/etc.) and a
        # customer notification email. Both are integration hook points,
        # left as TODOs for the real deployment.
        return req
