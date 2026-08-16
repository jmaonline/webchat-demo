"""
Tests the FastAPI admin endpoints (approval queue) directly — no LLM
needed. The /api/chat endpoint is exercised via a monkeypatched agent so
this also runs without an API key.

Run with: pytest tests/test_api.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from backend import app as app_module
from backend import approval_queue


client = TestClient(app_module.app)


def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_chat_endpoint_with_stubbed_agent(monkeypatch):
    class StubAgent:
        def send(self, message, **kwargs):
            return f"stub reply to: {message}"

    monkeypatch.setitem(app_module._SESSIONS, "fixed-session", StubAgent())

    res = client.post("/api/chat", json={"session_id": "fixed-session", "message": "hi"})
    assert res.status_code == 200
    body = res.json()
    assert body["session_id"] == "fixed-session"
    assert body["reply"] == "stub reply to: hi"


def test_admin_approval_flow():
    req = approval_queue.create_return_refund_request(
        order_id="BK-10021",
        customer_email="jane.doe@example.com",
        item_title="The Midnight Library",
        reason="test reason",
        requested_refund_amount=19.99,
    )

    res = client.get("/api/admin/approvals", params={"status": "pending"})
    assert res.status_code == 200
    ids = [r["request_id"] for r in res.json()["requests"]]
    assert req["request_id"] in ids

    res = client.post(
        f"/api/admin/approvals/{req['request_id']}/approve",
        json={"resolved_by": "staff_test", "notes": "looks good"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "approved"


def test_admin_approval_not_found():
    res = client.post("/api/admin/approvals/RT-00000/approve", json={})
    assert res.status_code == 404


def test_widget_served_at_root():
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "Bookly" in res.text


def test_admin_ui_served():
    res = client.get("/admin")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "Support Admin" in res.text


def test_admin_endpoints_require_token_when_configured(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "s3cret")

    # No header -> unauthorized
    res = client.get("/api/admin/approvals")
    assert res.status_code == 401

    # Wrong header -> unauthorized
    res = client.get("/api/admin/approvals", headers={"X-Admin-Token": "wrong"})
    assert res.status_code == 401

    # Correct header -> allowed
    res = client.get("/api/admin/approvals", headers={"X-Admin-Token": "s3cret"})
    assert res.status_code == 200


def test_admin_orders_endpoint_returns_mock_orders():
    res = client.get("/api/admin/orders")
    assert res.status_code == 200
    orders = res.json()["orders"]
    assert len(orders) == 5
    order_ids = {o["order_id"] for o in orders}
    assert "BK-10021" in order_ids


def test_admin_orders_endpoint_requires_token_when_configured(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "s3cret")

    res = client.get("/api/admin/orders")
    assert res.status_code == 401

    res = client.get("/api/admin/orders", headers={"X-Admin-Token": "s3cret"})
    assert res.status_code == 200


def test_embed_widget_served():
    res = client.get("/embed")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "chat-launcher" in res.text
    # The bare embed page must NOT include the landing-page chrome —
    # it's meant to be just the bubble+panel inside an iframe.
    assert "quick-links" not in res.text
    assert "Help Center" not in res.text


def test_embed_js_served_with_correct_content_type():
    res = client.get("/embed.js")
    assert res.status_code == 200
    assert "javascript" in res.headers["content-type"]
    assert "bookly-widget" in res.text
    assert "/embed" in res.text
