"""
FastAPI backend exposing:
  GET  /                                  - the chat widget itself (self-hosted)
  GET  /embed                             - bare chat bubble+panel, loaded in an iframe by /embed.js
  GET  /embed.js                          - drop-in <script> loader for embedding the widget on any site
  POST /api/chat                          - customer-facing chat endpoint
  GET  /api/admin/approvals               - list pending/all approval requests
  POST /api/admin/approvals/{id}/approve  - human approves a return/refund
  POST /api/admin/approvals/{id}/deny     - human denies a return/refund
  GET  /api/admin/orders                  - list all orders (from the Google Sheet / local fallback)
  GET  /api/admin/sessions                - list recent chat sessions (requires Postgres, see db.py)
  GET  /api/admin/sessions/{id}           - full transcript for one chat session

Session state (conversation history per customer) is kept in an in-memory
dict here for fast access *within* a running process. When DATABASE_URL is
set (see db.py, render.yaml), every turn is also persisted to Postgres, so
a conversation survives a restart/redeploy and staff can review past
transcripts via GET /api/admin/sessions[...]. Without DATABASE_URL set,
persistence is skipped entirely and behavior is unchanged (in-memory only,
resets on restart) — fine for local dev/tests.

Admin endpoints are protected by a shared-secret header (X-Admin-Token)
when ADMIN_API_TOKEN is set in the environment. Set this before deploying
publicly — see DEPLOY.md. If it's unset, admin endpoints are open (fine
for local-only testing, NOT fine once this is reachable on the internet).
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import approval_queue, db
from .agent import SupportAgent
from .tools import data_store

app = FastAPI(title="Bookly Support Agent")

if not os.environ.get("ADMIN_API_TOKEN"):
    print(
        "[startup warning] ADMIN_API_TOKEN is not set — /api/admin/* endpoints are "
        "UNAUTHENTICATED. Fine for local testing, do NOT deploy publicly like this."
    )

# Wide open for local/dev demo purposes, and fine for this single-origin
# deployment (widget is served from this same app). If you split the
# widget out to your real storefront's own domain, set allow_origins to
# that domain explicitly instead of "*".
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_SESSIONS: dict[str, SupportAgent] = {}
_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
_WIDGET_PATH = _FRONTEND_DIR / "widget.html"
_ADMIN_PATH = _FRONTEND_DIR / "admin.html"
_EMBED_WIDGET_PATH = _FRONTEND_DIR / "embed-widget.html"
_EMBED_JS_PATH = _FRONTEND_DIR / "embed.js"


def require_admin(x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> None:
    expected = os.environ.get("ADMIN_API_TOKEN")
    if expected and x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Missing or invalid X-Admin-Token header")


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str


class ResolveRequest(BaseModel):
    resolved_by: str = "support-staff"
    notes: str = ""


@app.get("/")
def widget():
    """Serves the chat widget itself, so the whole app is reachable from one URL."""
    return FileResponse(_WIDGET_PATH)


@app.get("/admin")
def admin_ui():
    """
    Serves the staff admin page for reviewing/approving return-refund
    requests. The page itself has no secrets in it — it prompts whoever
    loads it for the ADMIN_API_TOKEN client-side and sends it as a header
    on each API call, which is what actually enforces access control.
    """
    return FileResponse(_ADMIN_PATH)


@app.get("/embed")
def embed_widget():
    """
    Bare chat bubble+panel, no landing-page chrome — this is what
    /embed.js loads inside an iframe on third-party sites. Not meant to
    be visited directly (though nothing bad happens if you do).
    """
    return FileResponse(_EMBED_WIDGET_PATH)


@app.get("/embed.js")
def embed_js():
    """
    Drop-in loader script for embedding the chat widget on ANY website:
        <script src="https://<this-app>/embed.js" async></script>
    Injects a floating iframe pointing at /embed and resizes it between
    bubble/panel size via postMessage. See frontend/embed.js for details.
    """
    return FileResponse(_EMBED_JS_PATH, media_type="application/javascript")


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or str(uuid.uuid4())
    agent = _SESSIONS.get(session_id)
    if agent is None:
        agent = SupportAgent()
        # Not in this process's memory — e.g. after a restart/redeploy.
        # Try to resume the conversation from Postgres before starting a
        # brand-new one. No-op (returns None) if persistence isn't
        # configured or this session was never saved.
        saved_messages = db.load_session(session_id)
        if saved_messages:
            agent.load_messages(saved_messages)
        _SESSIONS[session_id] = agent

    reply = agent.send(req.message)

    # Best-effort persistence: never let a DB hiccup break the customer's
    # chat response. No-op if DATABASE_URL isn't configured.
    try:
        db.save_session(session_id, agent.to_serializable_messages())
    except Exception as e:  # noqa: BLE001
        print(f"[warning] failed to persist session {session_id}: {e}")

    return ChatResponse(session_id=session_id, reply=reply)


@app.get("/api/admin/approvals", dependencies=[Depends(require_admin)])
def list_approvals(status: str | None = None):
    return {"requests": approval_queue.list_requests(status=status)}


@app.post("/api/admin/approvals/{request_id}/approve", dependencies=[Depends(require_admin)])
def approve(request_id: str, body: ResolveRequest):
    result = approval_queue.resolve_request(
        request_id, approve=True, resolved_by=body.resolved_by, notes=body.notes
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Request not found")
    return result


@app.post("/api/admin/approvals/{request_id}/deny", dependencies=[Depends(require_admin)])
def deny(request_id: str, body: ResolveRequest):
    result = approval_queue.resolve_request(
        request_id, approve=False, resolved_by=body.resolved_by, notes=body.notes
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Request not found")
    return result


@app.get("/api/admin/orders", dependencies=[Depends(require_admin)])
def list_orders():
    """
    All orders as currently known to the agent (from the Google Sheet if
    configured, otherwise the local mock_data/orders.json fallback) — lets
    staff sanity-check what the agent sees without opening the sheet.
    Read-only; editing still happens in the sheet (or the JSON file), not
    here.
    """
    return {"orders": data_store.get_all_orders()}


@app.get("/api/admin/sessions", dependencies=[Depends(require_admin)])
def list_sessions():
    """
    Recent chat sessions (id, timestamps, message count), most-recently-
    active first — lets staff spot-check what customers are asking Bucky.
    Requires Postgres persistence to be configured (DATABASE_URL); returns
    an empty list otherwise rather than erroring, since this is an
    optional feature.
    """
    return {"sessions": db.list_sessions()}


@app.get("/api/admin/sessions/{session_id}", dependencies=[Depends(require_admin)])
def get_session_transcript(session_id: str):
    """Full message history for one chat session, as persisted to Postgres."""
    messages = db.load_session(session_id)
    if messages is None:
        raise HTTPException(status_code=404, detail="Session not found (or Postgres persistence isn't configured)")
    return {"session_id": session_id, "messages": messages}


@app.get("/api/health")
def health():
    return {"status": "ok"}
