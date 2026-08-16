"""
Agent core: system prompt, tool schemas, and the tool-use loop against the
Anthropic Messages API. See docs/ARCHITECTURE.md §3 for design rationale.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable

import anthropic

from .tools import account_tools, order_tools, policy_tools, returns_tools

MODEL = os.environ.get("SUPPORT_AGENT_MODEL", "claude-sonnet-4-5-20250929")

SYSTEM_PROMPT = """\
You are Bucky, the customer support agent for Bookly, an online bookstore. \
You help customers with order status, returns/refunds, and general \
questions about shipping, policies, and account/password issues.

Ground rules — follow these strictly:

1. Only state facts that come from a tool result or the policy knowledge \
base. Never guess or invent order details, tracking numbers, dates, or \
policy terms.
2. Before revealing any order details, you must have both the order ID and \
the email address on that order, and confirm them via get_order_status or \
check_return_eligibility (which verify the match). If a customer only has \
an email, use find_orders_by_email to help them find the order first.
3. You can NEVER approve, process, or promise a refund or return yourself. \
Your only action is to check eligibility (check_return_eligibility) and, if \
the customer confirms they want to proceed, submit the request for human \
review (submit_return_request). Always tell the customer their request has \
been "submitted for review" — never "approved," "processed," or "refunded."
4. For password reset requests, call initiate_password_reset and relay its \
customer_message to the customer verbatim (word for word) — do not \
editorialize on whether the email was actually found, even if you can see \
that internally. This protects customer privacy.
5. For general questions about shipping, returns policy, payment methods, \
etc., use search_policy_kb and answer from the returned entries. If nothing \
relevant is found, say you're not sure and offer to connect them with a \
human.
6. If a request is outside what your tools can resolve (e.g. a dispute \
requiring judgment, anger/abuse, legal threats, or the customer explicitly \
asks for a human), call escalate_to_human and let the customer know a team \
member will follow up.
7. Be warm, concise, and professional. Avoid corporate filler. Don't dump \
every tool field on the customer — summarize what matters to their \
question.
8. If required identifying info (order ID, email) is missing, ask for it \
before calling tools that need it.
"""

TOOLS: list[dict] = [
    {
        "name": "get_order_status",
        "description": "Look up a single order's status, items, and tracking info by order ID and the email used on that order.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The bookstore order ID, e.g. BK-10021."},
                "customer_email": {"type": "string", "description": "The email address on the order."},
            },
            "required": ["order_id", "customer_email"],
        },
    },
    {
        "name": "find_orders_by_email",
        "description": "List a customer's recent orders by their account email, for when they don't have the order number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_email": {"type": "string", "description": "The customer's account email."},
            },
            "required": ["customer_email"],
        },
    },
    {
        "name": "check_return_eligibility",
        "description": "Check whether an order is eligible for return/refund under policy (delivered, within return window, not already returned).",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "customer_email": {"type": "string"},
            },
            "required": ["order_id", "customer_email"],
        },
    },
    {
        "name": "submit_return_request",
        "description": (
            "Submit a return/refund request for HUMAN REVIEW after eligibility has been confirmed and the "
            "customer has explicitly agreed to proceed. This does NOT process a refund itself — it only queues "
            "the request for staff approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "customer_email": {"type": "string"},
                "item_title": {"type": "string", "description": "Which item to return, or 'all items'."},
                "reason": {"type": "string", "description": "The customer's stated reason for the return."},
            },
            "required": ["order_id", "customer_email", "item_title", "reason"],
        },
    },
    {
        "name": "search_policy_kb",
        "description": "Search the shipping/returns/general policy FAQ knowledge base for an answer to a customer's question.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The customer's question or topic, in natural language."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "initiate_password_reset",
        "description": "Trigger a password reset email for the given account email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_email": {"type": "string"},
            },
            "required": ["customer_email"],
        },
    },
    {
        "name": "escalate_to_human",
        "description": "Flag this conversation for a human support agent to follow up, for requests outside what your tools can resolve.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Brief summary of why this needs human follow-up."},
            },
            "required": ["reason"],
        },
    },
]


def escalate_to_human(reason: str) -> dict:
    """Mock: in production this would create a ticket / notify a human queue."""
    return {
        "escalated": True,
        "message": "This conversation has been flagged for a support team member to follow up.",
        "reason": reason,
    }


_TOOL_IMPL: dict[str, Callable[..., dict]] = {
    "get_order_status": order_tools.get_order_status,
    "find_orders_by_email": order_tools.find_orders_by_email,
    "check_return_eligibility": returns_tools.check_return_eligibility,
    "submit_return_request": returns_tools.submit_return_request,
    "search_policy_kb": policy_tools.search_policy_kb,
    "initiate_password_reset": account_tools.initiate_password_reset,
    "escalate_to_human": escalate_to_human,
}


def _serialize_content(content: Any) -> Any:
    """
    Normalize one message's `content` into plain JSON-safe data.

    Anthropic API message content is either a plain string, or a list of
    content blocks. Blocks coming *out* of the SDK (assistant turns, i.e.
    `response.content`) are pydantic objects (TextBlock/ToolUseBlock/...);
    blocks we build ourselves (tool_result turns) are already plain dicts.
    This lets a conversation be persisted (e.g. to Postgres, see db.py) and
    later replayed by feeding the same plain dicts back to the API.
    """
    if isinstance(content, str):
        return content
    serialized = []
    for block in content:
        if isinstance(block, dict):
            serialized.append(block)
        elif hasattr(block, "model_dump"):
            serialized.append(block.model_dump(mode="json"))
        else:
            serialized.append(dict(vars(block)))  # best-effort fallback (e.g. test doubles)
    return serialized


def _execute_tool(name: str, tool_input: dict[str, Any]) -> dict:
    impl = _TOOL_IMPL.get(name)
    if impl is None:
        return {"error": "unknown_tool", "message": f"No such tool: {name}"}
    try:
        return impl(**tool_input)
    except TypeError as e:
        return {"error": "bad_arguments", "message": str(e)}
    except Exception as e:  # noqa: BLE001 - surface as a tool error, not a crash
        return {"error": "tool_execution_error", "message": str(e)}


class SupportAgent:
    """
    Wraps a conversation with the Claude tool-use loop. One instance per
    chat session (see app.py for session management).
    """

    def __init__(self, client: anthropic.Anthropic | None = None, model: str = MODEL):
        self.client = client or anthropic.Anthropic()
        self.model = model
        self.messages: list[dict] = []
        self.tool_call_log: list[dict] = []  # for debugging/tests: every tool call + result

    def to_serializable_messages(self) -> list[dict]:
        """
        A plain-JSON snapshot of the conversation so far — safe to persist
        (e.g. to Postgres, see db.py) and later hand to load_messages() to
        resume this exact conversation in a new SupportAgent instance.
        """
        return [{"role": m["role"], "content": _serialize_content(m["content"])} for m in self.messages]

    def load_messages(self, messages: list[dict]) -> None:
        """Restore a conversation previously captured by to_serializable_messages()."""
        self.messages = messages

    def send(self, user_message: str, max_tool_iterations: int = 6) -> str:
        self.messages.append({"role": "user", "content": user_message})

        for _ in range(max_tool_iterations):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=self.messages,
            )

            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                return "".join(block.text for block in response.content if block.type == "text")

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                result = _execute_tool(block.name, block.input)
                self.tool_call_log.append({"tool": block.name, "input": block.input, "result": result})
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    }
                )

            self.messages.append({"role": "user", "content": tool_results})

        return (
            "Sorry, I'm having trouble completing that request right now — "
            "let me flag this for a team member to help."
        )
