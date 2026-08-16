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
    assert "Sessions" in res.text  # sessions tab, backed by /api/admin/sessions


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


def test_admin_sessions_endpoint_empty_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    res = client.get("/api/admin/sessions")
    assert res.status_code == 200
    assert res.json() == {"sessions": []}


def test_admin_session_transcript_404_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    res = client.get("/api/admin/sessions/does-not-exist")
    assert res.status_code == 404


def test_admin_sessions_endpoint_requires_token_when_configured(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "s3cret")
    res = client.get("/api/admin/sessions")
    assert res.status_code == 401
    res = client.get("/api/admin/sessions", headers={"X-Admin-Token": "s3cret"})
    assert res.status_code == 200


def test_chat_endpoint_persists_session_when_database_configured(monkeypatch):
    """
    The chat endpoint should call db.save_session() after every turn (and
    db.load_session() on a cache miss) — verified here against a fake db
    module so no real Postgres is needed.
    """
    saved = {}

    def fake_save_session(session_id, messages):
        saved[session_id] = messages

    def fake_load_session(session_id):
        return saved.get(session_id)

    monkeypatch.setattr(app_module.db, "save_session", fake_save_session)
    monkeypatch.setattr(app_module.db, "load_session", fake_load_session)

    class StubAgent:
        def __init__(self):
            self.messages = []

        def send(self, message, **kwargs):
            self.messages.append({"role": "user", "content": message})
            return f"stub reply to: {message}"

        def to_serializable_messages(self):
            return self.messages

        def load_messages(self, messages):
            self.messages = messages

    monkeypatch.setattr(app_module, "SupportAgent", StubAgent)
    app_module._SESSIONS.pop("persisted-session", None)  # ensure a cache miss

    res = client.post("/api/chat", json={"session_id": "persisted-session", "message": "hello"})
    assert res.status_code == 200
    assert saved["persisted-session"] == [{"role": "user", "content": "hello"}]


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
