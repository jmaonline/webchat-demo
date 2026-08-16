"""
Unit tests for the mock backend tool functions — no LLM/API key required.
Run with: pytest tests/test_tools.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import approval_queue
from backend.tools import account_tools, order_tools, policy_tools, returns_tools


# ---- order_tools ------------------------------------------------------

def test_get_order_status_success():
    result = order_tools.get_order_status("BK-10021", "jane.doe@example.com")
    assert "order" in result
    assert result["order"]["status"] == "delivered"


def test_get_order_status_case_insensitive_id():
    result = order_tools.get_order_status("bk-10021", "jane.doe@example.com")
    assert "order" in result


def test_get_order_status_wrong_email():
    result = order_tools.get_order_status("BK-10021", "wrong@example.com")
    assert result.get("error") == "email_mismatch"


def test_get_order_status_not_found():
    result = order_tools.get_order_status("BK-99999", "jane.doe@example.com")
    assert result.get("error") == "not_found"


def test_find_orders_by_email():
    result = order_tools.find_orders_by_email("mchen88@example.com")
    assert result["count"] == 2
    order_ids = {o["order_id"] for o in result["orders"]}
    assert order_ids == {"BK-10022", "BK-10024"}


def test_find_orders_by_email_no_match():
    result = order_tools.find_orders_by_email("nobody@example.com")
    assert result["count"] == 0


# ---- returns_tools ------------------------------------------------------

def test_return_eligibility_delivered_within_window():
    # BK-10021 delivered 2026-08-09, well within 30 days of "today" in tests
    result = returns_tools.check_return_eligibility("BK-10021", "jane.doe@example.com")
    assert result["eligible"] is True


def test_return_eligibility_not_delivered_yet():
    result = returns_tools.check_return_eligibility("BK-10022", "mchen88@example.com")
    assert result["eligible"] is False
    assert "hasn't been delivered" in result["reason"]


def test_return_eligibility_cancelled_order():
    result = returns_tools.check_return_eligibility("BK-10024", "mchen88@example.com")
    assert result["eligible"] is False
    assert "cancelled" in result["reason"].lower()


def test_return_eligibility_already_returned():
    result = returns_tools.check_return_eligibility("BK-10018", "priya.k@example.com")
    assert result["eligible"] is False
    assert "already" in result["reason"].lower()


def test_return_eligibility_email_mismatch():
    result = returns_tools.check_return_eligibility("BK-10021", "someone-else@example.com")
    assert result.get("error") == "email_mismatch"


def test_submit_return_request_creates_pending_approval():
    result = returns_tools.submit_return_request(
        order_id="BK-10021",
        customer_email="jane.doe@example.com",
        item_title="The Midnight Library",
        reason="Changed my mind",
    )
    assert result["status"] == "pending"
    request_id = result["request_id"]

    stored = approval_queue.get_request(request_id)
    assert stored is not None
    assert stored["status"] == "pending"
    assert stored["order_id"] == "BK-10021"
    assert stored["requested_refund_amount"] == 19.99


def test_submit_return_request_all_items_uses_order_total():
    result = returns_tools.submit_return_request(
        order_id="BK-10018",
        customer_email="priya.k@example.com",
        item_title="all items",
        reason="Wrong items shipped",
    )
    stored = approval_queue.get_request(result["request_id"])
    assert stored["requested_refund_amount"] == 45.00


# ---- approval_queue ------------------------------------------------------

def test_approval_queue_approve_flow():
    created = approval_queue.create_return_refund_request(
        order_id="BK-10021",
        customer_email="jane.doe@example.com",
        item_title="Project Hail Mary",
        reason="Damaged on arrival",
        requested_refund_amount=22.50,
    )
    assert created["status"] == "pending"

    resolved = approval_queue.resolve_request(
        created["request_id"], approve=True, resolved_by="staff_alice", notes="Confirmed via photo"
    )
    assert resolved["status"] == "approved"
    assert resolved["resolved_by"] == "staff_alice"

    # idempotent: resolving again doesn't flip it back
    again = approval_queue.resolve_request(created["request_id"], approve=False, resolved_by="staff_bob")
    assert again["status"] == "approved"


def test_approval_queue_deny_flow():
    created = approval_queue.create_return_refund_request(
        order_id="BK-10021",
        customer_email="jane.doe@example.com",
        item_title="Project Hail Mary",
        reason="Just don't want it",
        requested_refund_amount=22.50,
    )
    resolved = approval_queue.resolve_request(created["request_id"], approve=False, resolved_by="staff_alice")
    assert resolved["status"] == "denied"


def test_approval_queue_unknown_id():
    assert approval_queue.resolve_request("RT-99999", approve=True, resolved_by="x") is None


# ---- policy_tools ------------------------------------------------------

def test_policy_search_returns_policy():
    result = policy_tools.search_policy_kb("How many days do I have to return a book?")
    assert result["found"] is True
    assert any("30 days" in e["answer"] for e in result["results"])


def test_policy_search_password_reset():
    result = policy_tools.search_policy_kb("I forgot my password, how do I reset it?")
    assert result["found"] is True
    assert any("reset" in e["question"].lower() for e in result["results"])


def test_policy_search_no_match():
    result = policy_tools.search_policy_kb("xyzzyplugh quantum flux capacitor")
    assert result["found"] is False


# ---- account_tools ------------------------------------------------------

def test_password_reset_existing_email_neutral_message():
    result = account_tools.initiate_password_reset("jane.doe@example.com")
    assert result["matched"] is True
    assert "if that email is on file" in result["customer_message"].lower()


def test_password_reset_unknown_email_same_neutral_message():
    result = account_tools.initiate_password_reset("nobody@example.com")
    assert result["matched"] is False
    # Message text must be identical regardless of match, to avoid account enumeration
    matched_msg = account_tools.initiate_password_reset("jane.doe@example.com")["customer_message"]
    assert result["customer_message"] == matched_msg
