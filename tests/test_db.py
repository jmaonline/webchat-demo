"""
Tests backend/db.py's optional Postgres persistence layer WITHOUT a real
database — no network/DB connection is available in CI/test environments.

Two things are covered:
  1. The disabled path (no DATABASE_URL, or psycopg2 unavailable): every
     function must be a safe no-op, never raise.
  2. The enabled path: a fake psycopg2 module stands in for the real one,
     so we can assert the right SQL shape runs without needing a live DB.

Run with: pytest tests/test_db.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import db


# ---- Disabled path: no DATABASE_URL set ----------------------------------


def test_save_session_is_noop_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # Should not raise even though nothing is configured.
    db.save_session("some-session", [{"role": "user", "content": "hi"}])


def test_load_session_returns_none_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert db.load_session("some-session") is None


def test_list_sessions_returns_empty_list_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert db.list_sessions() == []


def test_disabled_when_psycopg2_unavailable_even_with_url_set(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setattr(db, "psycopg2", None)
    assert db.load_session("x") is None
    assert db.list_sessions() == []
    db.save_session("x", [])  # must not raise


# ---- Enabled path: fake psycopg2 stands in for the real driver -----------


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._conn.executed.append((" ".join(sql.split()), params))
        if "INSERT INTO chat_sessions" in sql:
            session_id, messages_json = params[0], params[1]
            value = messages_json.value if isinstance(messages_json, _FakeJson) else messages_json
            self._conn.store[session_id] = value
        elif "SELECT messages FROM chat_sessions" in sql:
            session_id = params[0]
            row = self._conn.store.get(session_id)
            self._last_result = [(row,)] if row is not None else []
        elif "FROM chat_sessions" in sql and "ORDER BY updated_at" in sql:
            self._last_result = [
                {"session_id": sid, "created_at": "t", "updated_at": "t", "message_count": len(msgs)}
                for sid, msgs in self._conn.store.items()
            ]
        else:
            self._last_result = []

    def fetchone(self):
        return self._last_result[0] if self._last_result else None

    def fetchall(self):
        return self._last_result


class _FakeConn:
    def __init__(self, store):
        self.store = store
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self, cursor_factory=None):
        return _FakeCursor(self)

    def close(self):
        pass


class _FakeJson:
    """Stand-in for psycopg2.extras.Json — just remembers the value."""

    def __init__(self, value):
        self.value = value


class _FakePsycopg2Module:
    def __init__(self):
        self.store: dict[str, list] = {}
        self.extras = type("extras", (), {"Json": _FakeJson, "RealDictCursor": object()})()

    def connect(self, dsn):
        return _FakeConn(self.store)


def _install_fake_psycopg2(monkeypatch):
    fake = _FakePsycopg2Module()
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setattr(db, "psycopg2", fake)
    monkeypatch.setattr(db, "_initialized", False)
    return fake


def test_save_then_load_session_round_trips(monkeypatch):
    _install_fake_psycopg2(monkeypatch)
    messages = [{"role": "user", "content": "Where's my order?"}]

    db.save_session("sess-1", messages)
    loaded = db.load_session("sess-1")

    assert loaded == messages


def test_load_session_missing_returns_none(monkeypatch):
    _install_fake_psycopg2(monkeypatch)
    assert db.load_session("nonexistent") is None


def test_list_sessions_reflects_store(monkeypatch):
    fake = _install_fake_psycopg2(monkeypatch)
    fake.store["a"] = [{"role": "user", "content": "hi"}]
    fake.store["b"] = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]

    sessions = db.list_sessions()
    counts = {s["session_id"]: s["message_count"] for s in sessions}
    assert counts == {"a": 1, "b": 2}
