"""
FastAPI backend exposing:
  GET  /                                  - the chat widget itself (self-hosted)
  POST /api/chat                          - customer-facing chat endpoint
  GET  /api/admin/approvals               - list pending/all approval requests
  POST /api/admin/approvals/{id}/approve  - human approves a return/refund
  POST /api/admin/approvals/{id}/deny     - human denies a return/refund

Session state (conversation history per customer) is kept in memory here
for the prototype — swap for Redis/a DB for production so it survives
restarts and scales across workers.

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

from . import approval_queue
from .agent import SupportAgent

app = FastAPI(title="Bookworm Haven Support Agent")

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
_WIDGET_PATH = Path(__file__).resolve().parent.parent / "frontend" / "widget.html"


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


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or str(uuid.uuid4())
    agent = _SESSIONS.get(session_id)
    if agent is None:
        agent = SupportAgent()
        _SESSIONS[session_id] = agent

    reply = agent.send(req.message)
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


@app.get("/api/health")
def health():
    return {"status": "ok"}
