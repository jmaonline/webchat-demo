"""
Optional Postgres-backed persistence for chat sessions.

This solves two gaps the in-memory `_SESSIONS` dict in app.py has on its
own:
  1. Conversations survive a restart/redeploy. Render's web service (even
     paid plans, and especially the free plan) restarts periodically —
     without this, every in-progress chat would silently reset.
  2. There's a permanent, queryable record of every conversation, so staff
     can review what customers asked and how the agent responded (see the
     GET /api/admin/sessions[...] endpoints in app.py).

Controlled entirely by the DATABASE_URL environment variable (Render sets
this automatically once a Postgres database is attached — see
render.yaml and DEPLOY.md). If it's unset, or the `psycopg2` package isn't
installed, every function below becomes a safe no-op and the app behaves
exactly as before: in-memory only, nothing persisted. This mirrors the
same fallback pattern used for Google Sheets in tools/data_store.py — the
app should never hard-fail just because optional persistence isn't
configured (e.g. running locally, or in tests).

Schema is a single table, created on first use:

    chat_sessions (
        session_id  TEXT PRIMARY KEY,
        messages    JSONB NOT NULL,   -- SupportAgent.to_serializable_messages()
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )

This is intentionally simple (one connection per call, no pooling) — fine
for a support-widget prototype's traffic. A real production deployment
would swap this for a connection pool (e.g. psycopg_pool) if volume grows.
"""
from __future__ import annotations

import os
from typing import Optional

try:
    import psycopg2
    import psycopg2.extras
except ImportError:  # pragma: no cover - psycopg2 is an optional dependency
    psycopg2 = None  # type: ignore[assignment]

_initialized = False


def _database_url() -> Optional[str]:
    # Read live (not at import time) so tests can monkeypatch this env var,
    # same pattern as ADMIN_API_TOKEN in app.py.
    return os.environ.get("DATABASE_URL")


def _enabled() -> bool:
    return psycopg2 is not None and bool(_database_url())


def _get_conn():
    return psycopg2.connect(_database_url())


def _ensure_schema() -> None:
    global _initialized
    if _initialized or not _enabled():
        return
    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chat_sessions (
                        session_id TEXT PRIMARY KEY,
                        messages JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
        _initialized = True
    finally:
        conn.close()


def save_session(session_id: str, messages: list[dict]) -> None:
    """Upsert the full message history for a session. No-op if Postgres
    persistence isn't configured."""
    if not _enabled():
        return
    _ensure_schema()
    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chat_sessions (session_id, messages, updated_at)
                    VALUES (%s, %s, now())
                    ON CONFLICT (session_id)
                    DO UPDATE SET messages = EXCLUDED.messages, updated_at = now()
                    """,
                    (session_id, psycopg2.extras.Json(messages)),
                )
    finally:
        conn.close()


def load_session(session_id: str) -> Optional[list[dict]]:
    """Fetch a previously-saved session's message history, or None if the
    session isn't found, or Postgres persistence isn't configured."""
    if not _enabled():
        return None
    _ensure_schema()
    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT messages FROM chat_sessions WHERE session_id = %s", (session_id,))
                row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def list_sessions(limit: int = 50) -> list[dict]:
    """Most-recently-updated sessions (id, timestamps, message count) for
    the admin transcript viewer. Empty list if persistence isn't
    configured."""
    if not _enabled():
        return []
    _ensure_schema()
    conn = _get_conn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT session_id, created_at, updated_at,
                           jsonb_array_length(messages) AS message_count
                    FROM chat_sessions
                    ORDER BY updated_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
