# Bookly — Customer Support Agent (Prototype)

A tool-calling AI support agent for an online bookstore. Handles order
status, returns/refunds (with human approval), and general policy/FAQ
questions, via an embeddable web chat widget.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design
rationale, tool contracts, and notes on swapping the mock backend for real
systems (Shopify, a custom OMS, Zendesk, your auth provider, etc.).

## What's here

```
backend/
  agent.py           - system prompt, tool schemas, tool-use loop (SupportAgent)
  app.py             - FastAPI server: /api/chat + admin approval endpoints
  approval_queue.py  - human-in-the-loop queue for refunds/returns
  db.py              - optional Postgres persistence for chat sessions (no-op if DATABASE_URL unset)
  chat_cli.py         - terminal chat harness for manual testing with a real API key
  tools/
    order_tools.py     - order status lookup
    returns_tools.py   - return eligibility + submit request (queues, never executes)
    policy_tools.py    - FAQ/policy knowledge base search
    account_tools.py   - password reset initiation
    data_store.py       - mock data access layer (swap point for real systems)
  mock_data/
    orders.json, customers.json, policy_kb.md   - local fallback data
    sheets_export/                              - CSVs to import into Google Sheets (optional)
frontend/
  widget.html         - main site (Help Center landing page + chat), served at /
  admin.html          - staff admin page for approving/denying return requests + browsing orders
  embed-widget.html   - bare chat bubble+panel (no landing page), served at /embed
  embed.js            - drop-in <script> loader for embedding the widget on any other site
tests/
  test_tools.py               - unit tests for all backend tool functions (no API key needed)
  test_agent_loop.py          - tests the tool-use loop logic with a stubbed Claude client
  test_agent_serialization.py - tests conversation serialize/restore for Postgres persistence
  test_api.py                 - tests the FastAPI endpoints (including /embed, /embed.js)
  test_data_store_sheets.py   - tests the Google Sheets CSV parsing + fallback logic
  test_db.py                  - tests backend/db.py's persistence layer with a fake Postgres driver
docs/
  ARCHITECTURE.md          - full design doc
  GOOGLE_SHEETS_SETUP.md   - optional: point test data at a Google Sheet instead of local JSON
  EMBEDDING.md             - how to embed the widget on any other website
  embed-demo.html           - example of the widget embedded on a fake unrelated site
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
cp .env.example .env   # then fill in your ANTHROPIC_API_KEY
export ANTHROPIC_API_KEY=sk-ant-...   # or `source .env` with your own loader
```

## Run the tests (no API key required)

```bash
pytest tests/ -v
```

All 61 tests should pass — they cover the mock backend tools, the
approval-queue human-in-the-loop flow, the agent's tool-dispatch loop
(against a stubbed Claude client, so no API calls/cost), the FastAPI
endpoints, and the optional Postgres persistence layer (tested against a
fake driver — no real database needed to run the suite).

## Try it in the terminal (requires a real API key)

```bash
python -m backend.chat_cli
```

Then try things like:
- `Hi, can you check on order BK-10021? My email is jane.doe@example.com`
- `I'd like to return the Project Hail Mary book from that order, it arrived damaged`
- `What's your shipping policy?`
- `I forgot my password, can you help?`

Sample accounts in the mock data (see `backend/mock_data/orders.json`):

| Email | Orders |
|---|---|
| jane.doe@example.com | BK-10021 (delivered), BK-10023 (processing) |
| mchen88@example.com | BK-10022 (shipped), BK-10024 (cancelled) |
| priya.k@example.com | BK-10018 (delivered, already has a completed return) |

## Run the full stack (backend + widget)

```bash
uvicorn backend.app:app --reload --port 8000
```

Then open `frontend/widget.html` directly in a browser (or serve it via any
static file server) — the backend URL field defaults to
`http://localhost:8000` and is editable in the widget's config bar for
easy local testing. Click the 💬 bubble bottom-right to start chatting.

## Reviewing/approving return requests (the human-in-the-loop step)

Refund/return requests never execute automatically. While the backend is
running:

```bash
# See pending requests
curl http://localhost:8000/api/admin/approvals?status=pending

# Approve one
curl -X POST http://localhost:8000/api/admin/approvals/RT-5100/approve \
  -H 'Content-Type: application/json' \
  -d '{"resolved_by": "your_name", "notes": "confirmed eligible"}'

# Or deny one
curl -X POST http://localhost:8000/api/admin/approvals/RT-5100/deny \
  -H 'Content-Type: application/json' \
  -d '{"resolved_by": "your_name", "notes": "outside return window"}'
```

In a real deployment, wire these into whatever tool your support team
already lives in (a Zendesk view, an internal admin dashboard, etc.)
instead of raw curl calls.

## Embedding the widget on any website

Drop the chat widget onto any external site with one line:
`<script src="https://<your-app>.onrender.com/embed.js" async></script>`.
See [`docs/EMBEDDING.md`](docs/EMBEDDING.md) for how it works and
`docs/embed-demo.html` for a working example on a fake unrelated site.

## Chat session persistence (optional, Postgres)

By default, chat sessions live only in server memory — they're lost if the
process restarts, and there's no record of past conversations. Setting
`DATABASE_URL` turns on Postgres persistence: every turn is saved, so a
conversation survives a restart and staff can review transcripts:

```bash
# Recent sessions (id, timestamps, message count)
curl http://localhost:8000/api/admin/sessions

# Full transcript for one session
curl http://localhost:8000/api/admin/sessions/<session_id>
```

Leave `DATABASE_URL` unset for local dev — everything falls back to
in-memory behavior automatically, no errors. On Render, `render.yaml`
provisions a free Postgres database and wires `DATABASE_URL` to it
automatically when you deploy the blueprint. **Heads up:** Render's free
Postgres plan expires 30 days after creation (data is deleted after a
14-day grace period) — fine for testing, but upgrade the database to a
paid plan in the Render dashboard before then if you want chat history to
stick around (upgrading in place keeps existing data).

## Using Google Sheets for test data (optional)

By default order/customer/return data comes from the local JSON files. You
can instead point it at a Google Sheet (handy for editing test orders
without touching code) — see
[`docs/GOOGLE_SHEETS_SETUP.md`](docs/GOOGLE_SHEETS_SETUP.md). CSVs ready to
import are in `backend/mock_data/sheets_export/`.

## Next steps toward production

See §7 and §9 of `docs/ARCHITECTURE.md` for the full list, in short:
connect real order/returns/policy/auth systems in place of the mocks, move
the approval queue to a real database (chat sessions can already
optionally persist to Postgres — see above), add authentication (both
customer login and admin-endpoint auth), lock down CORS, add logging/
observability, and decide on a notification channel for approval outcomes
(email the customer when their return is approved/denied).
