# Bookstore Customer Support Agent — Architecture

## 1. Overview

A tool-using AI agent (built on Claude via the Anthropic Messages API tool-calling
loop) that handles three classes of customer support requests for an online
bookstore:

1. **Order status inquiries** — "Where's my order?", "Has #12345 shipped?"
2. **Return / refund requests** — eligibility checks, initiating a return,
   requesting a refund
3. **General questions** — shipping policy, returns policy, password reset,
   other FAQ-style questions

The customer talks to the agent through a **web chat widget** embedded on the
bookstore site. The agent is **read/write for information**, but any action
with financial or account consequence (refunds, return approvals) is
**drafted by the agent and routed to a human-approval queue** rather than
executed automatically. Everything else (order lookups, policy answers,
starting a password reset email) the agent can do autonomously.

```
┌────────────┐      HTTPS       ┌───────────────────────┐
│  Web Chat  │ ───────────────▶ │   FastAPI backend      │
│  Widget    │ ◀─────────────── │   /api/chat             │
│ (browser)  │                  └───────────┬────────────┘
└────────────┘                              │
                                             ▼
                                  ┌───────────────────────┐
                                  │   Agent Core            │
                                  │  (tool-use loop calling │
                                  │   Claude Messages API)  │
                                  └───────────┬────────────┘
                                              │ tool calls
                        ┌─────────────────────┼─────────────────────┐
                        ▼                     ▼                     ▼
              ┌──────────────────┐ ┌────────────────────┐ ┌──────────────────┐
              │ Order system     │ │ Returns/Refunds     │ │ Policy / FAQ KB   │
              │ (lookup only)    │ │ (proposes actions,  │ │ (read only)       │
              │                  │ │  queues for human    │ │                   │
              │                  │ │  approval)           │ │                   │
              └──────────────────┘ └──────────┬──────────┘ └──────────────────┘
                                               │
                                               ▼
                                    ┌────────────────────┐
                                    │ Human Approval Queue│
                                    │  + Staff Admin UI    │
                                    │  (approve / deny)    │
                                    └────────────────────┘
```

In this build, "Order system", "Returns/Refunds", and "Policy / FAQ KB" are
**mocked** with realistic sample data and a clean function-call interface
(`backend/tools/*.py`). Each mock module is intentionally written so that
swapping in a real system later means rewriting the function body only — the
tool's name, inputs, and outputs (its "contract" with the agent) stay the
same. See §7 for what that swap looks like for common real systems
(Shopify, a custom order DB, Zendesk, etc.).

## 2. Why a tool-calling agent (not a flowchart/decision-tree bot)

A traditional decision-tree IVR-style bot forces the customer down rigid
paths ("Press 1 for orders..."). A tool-calling LLM agent instead:

- Understands free-form customer language ("the book I ordered Tuesday
  hasn't shown up") and maps it to the right tool call itself.
- Can combine steps in one turn (look up the order **and** check return
  eligibility **and** explain the policy, in one coherent reply).
- Handles multi-turn context ("actually, I meant order #4471, not #4470").
- Is easy to extend: adding a capability means adding a new tool function,
  not redrawing a flowchart.

The trade-off is that it needs guardrails: a strict system prompt, tools
that only return/act within scope, and a hard rule that money-moving actions
require human sign-off. That's the human-in-the-loop design in §4.

## 3. Agent core

Implementation: `backend/agent.py`. Uses the Anthropic Python SDK
(`anthropic` package) directly against the Messages API's native tool-use
support — this is the standard, portable pattern for a business/customer-
facing conversational agent with custom domain tools (order systems, refund
systems, etc.), and is what most production support agents are built on.

> **Note on "Claude Agent SDK":** Anthropic also ships a `claude-agent-sdk`
> package, but it's purpose-built for coding-agent workloads (filesystem,
> bash, subagents, hooks) like Claude Code itself. For a customer support
> bot whose "tools" are business API calls rather than a filesystem, the
> Messages API tool-use loop (what's implemented here) is the right fit and
> is fully compatible if you later want to layer this project into an
> Agent-SDK-based environment via MCP.

Loop:

1. Receive the customer's message (+ conversation history, kept server-side
   per session).
2. Call the Messages API with the system prompt, conversation, and the tool
   schemas (§5).
3. If Claude returns a `tool_use` block, execute the corresponding Python
   function, feed the `tool_result` back, and loop.
4. Once Claude returns a plain text response, send it to the widget.

The system prompt (in `backend/agent.py`) sets ground rules:

- Only answer from tool results / the policy KB — never invent order
  details, tracking numbers, or policy terms.
- Always verify the customer's identity (order number + email, or account
  email) before revealing order details.
- Never state that a refund/return has been approved or processed — only
  that it's been **submitted for review**, since actual execution requires
  human approval.
- Escalate to a human (via a clearly flagged message) for anything outside
  scope: damaged/wrong item disputes needing judgment calls, abuse, legal
  threats, anything the tools can't resolve.
- Keep a friendly, concise, bookstore-appropriate tone.

## 4. Human-in-the-loop approval

Per your requirement, **order status and general Q&A are fully autonomous**;
**refunds/returns always stop for human approval**. Mechanics:

1. Customer asks for a return/refund. Agent calls `check_return_eligibility`
   (read-only) to confirm the order qualifies (within window, not already
   returned, etc.) and explains this to the customer.
2. If eligible and the customer confirms they want to proceed, the agent
   calls `submit_return_request`, which **does not refund anything** — it
   writes a row to an approval queue (`backend/approval_queue.py`) with
   status `pending` and returns a request ID.
3. The agent tells the customer their request (ID) has been submitted and
   is under review, with an expected turnaround.
4. A staff member reviews pending requests via simple admin endpoints
   (`GET /api/admin/approvals`, `POST /api/admin/approvals/{id}/approve` or
   `/deny`) — a minimal JSON API here, meant to be wired into whatever
   internal tool support staff already uses (Zendesk, a spreadsheet, an
   internal dashboard).
5. On approval, the (mocked) refund is "processed" and the order record is
   updated; on denial, the customer would be notified (hook point noted in
   code — actual notification channel, e.g. email, is left to integration).

This keeps money-moving actions out of the LLM's hands entirely — the agent
can *propose*, never *execute*.

## 5. Tools exposed to the agent

| Tool | Type | Purpose |
|---|---|---|
| `get_order_status` | read | Look up an order by order ID + verifying email; returns status, items, tracking, dates |
| `find_orders_by_email` | read | List a customer's recent orders when they don't have the order number handy |
| `check_return_eligibility` | read | Given an order ID, determine if/why it qualifies for return within policy |
| `submit_return_request` | write → queued | Creates a pending return/refund request for human approval (never executes directly) |
| `search_policy_kb` | read | Semantic-ish lookup over shipping/returns/general policy FAQ content |
| `initiate_password_reset` | write (safe/idempotent) | Triggers a password reset email flow for a verified account email (no PII returned to the chat) |
| `escalate_to_human` | control | Agent-invoked flag when a request is out of scope or the customer explicitly asks for a person |

Full schemas are in `backend/agent.py` (`TOOLS` list) and implementations in
`backend/tools/`.

## 6. Data & privacy notes

- Identity check before disclosing order details: order ID **and** the
  email on the order must both match. This is a minimum bar for a
  prototype — a real deployment should use authenticated sessions
  (logged-in customer) wherever possible instead of order+email matching,
  which is guessable.
- `initiate_password_reset` never confirms whether an email exists in the
  system in its reply to the customer (prevents account enumeration) — it
  always replies with the same "if that email is on file, a reset link was
  sent" message, and only *internally* knows whether it matched.
- No payment card data is ever stored or handled — refunds go through the
  existing payment processor once a human approves; this agent only
  triggers/queues that action.

## 7. Swapping mocks for real systems

Each file in `backend/tools/` has a single function per tool with a
docstring describing its contract. To go from mock → real:

- **Order system** (`order_tools.py`): replace the JSON-file lookup with an
  API call to Shopify Admin API / a custom order service / your OMS.
  Contract (order ID, email in → status/items/tracking out) stays the same,
  so `agent.py` and the tool schema don't need to change.
- **Returns/Refunds** (`returns_tools.py`): `check_return_eligibility`
  becomes a real policy-engine or OMS call; `submit_return_request` still
  just writes to your approval queue (e.g. a Zendesk ticket, a Jira ticket,
  a row in your internal admin tool) — the "no direct execution" boundary
  should be preserved even with real systems.
- **Policy KB** (`policy_tools.py`): swap flat markdown for a real
  vector-search/RAG index over your help center content, or point it at
  Zendesk/Intercom Help Center's search API.
- **Password reset** (`account_tools.py`): call your real auth provider's
  reset-password API (Auth0, Cognito, custom auth service, etc.).

## 8. Channel: web chat widget

`frontend/widget.html` is a self-contained embeddable widget (inline CSS/JS,
no build step) that:

- Renders a chat bubble/button, expands to a chat panel.
- Maintains a `session_id` in memory for the page session.
- POSTs each customer message to `POST /api/chat` and renders the reply.
- Can be dropped into any page via an `<iframe>` or copied inline; for
  production you'd typically compile it into a small JS snippet
  (`<script src="widget.js">`) that injects the UI — noted as a follow-up.

## 9. What's out of scope for this build (explicitly)

- Real payment/refund execution (stops at "queued for human approval").
- Authentication/session management beyond a simple session ID (no login).
- Real policy-document RAG/embeddings (mock uses simple keyword search over
  a small markdown FAQ — swap-in point noted above).
- Multi-language support, voice/phone channel, proactive notifications
  (e.g. "your order shipped").
- Production concerns: persistent DB (uses in-memory/JSON for the
  prototype), authentication on admin endpoints, rate limiting, logging/
  observability, deployment/infra.

These are natural next steps once the core agent behavior is validated.
