# Bookworm Haven — Customer Support Agent (Prototype)

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
  chat_cli.py         - terminal chat harness for manual testing with a real API key
  tools/
    order_tools.py     - order status lookup
    returns_tools.py   - return eligibility + submit request (queues, never executes)
    policy_tools.py    - FAQ/policy knowledge base search
    account_tools.py   - password reset initiation
    data_store.py       - mock data access layer (swap point for real systems)
  mock_data/
    orders.json, customers.json, policy_kb.md
frontend/
  widget.html         - standalone embeddable chat widget (open directly in a browser)
tests/
  test_tools.py        - unit tests for all backend tool functions (no API key needed)
  test_agent_loop.py   - tests the tool-use loop logic with a stubbed Claude client
  test_api.py           - tests the FastAPI endpoints
docs/
  ARCHITECTURE.md      - full design doc
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

All 29 tests should pass — they cover the mock backend tools, the
approval-queue human-in-the-loop flow, the agent's tool-dispatch loop
(against a stubbed Claude client, so no API calls/cost), and the FastAPI
endpoints.

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

## Next steps toward production

See §7 and §9 of `docs/ARCHITECTURE.md` for the full list, in short:
connect real order/returns/policy/auth systems in place of the mocks,
move session state and the approval queue to a real database, add
authentication (both customer login and admin-endpoint auth), lock down
CORS, add logging/observability, and decide on a notification channel for
approval outcomes (email the customer when their return is approved/denied).
