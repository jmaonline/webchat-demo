"""
Tests SupportAgent.to_serializable_messages() / load_messages() — the pair
that lets a conversation be persisted (db.py) and resumed later, e.g.
after a Render restart. No real Anthropic API calls needed.

Run with: pytest tests/test_agent_serialization.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent import SupportAgent


class FakePydanticBlock:
    """Stands in for a real Anthropic SDK content block (TextBlock,
    ToolUseBlock, ...), which are pydantic models exposing model_dump()."""

    def __init__(self, **fields):
        self._fields = fields

    def model_dump(self, mode="json"):
        return dict(self._fields)


def test_to_serializable_messages_handles_plain_string_content():
    agent = SupportAgent.__new__(SupportAgent)  # skip __init__ (no API client needed)
    agent.messages = [{"role": "user", "content": "Where's my order?"}]

    serialized = agent.to_serializable_messages()

    assert serialized == [{"role": "user", "content": "Where's my order?"}]


def test_to_serializable_messages_converts_pydantic_blocks():
    agent = SupportAgent.__new__(SupportAgent)
    agent.messages = [
        {"role": "user", "content": "Check order BK-10021, jane.doe@example.com"},
        {
            "role": "assistant",
            "content": [
                FakePydanticBlock(type="tool_use", id="toolu_1", name="get_order_status", input={"order_id": "BK-10021"})
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "{}"}],
        },
    ]

    serialized = agent.to_serializable_messages()

    # Plain strings and already-plain dicts pass through untouched...
    assert serialized[0] == {"role": "user", "content": "Check order BK-10021, jane.doe@example.com"}
    assert serialized[2]["content"][0]["type"] == "tool_result"
    # ...pydantic-style blocks get flattened via model_dump().
    assert serialized[1]["content"][0] == {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "get_order_status",
        "input": {"order_id": "BK-10021"},
    }
    # The whole thing must be plain JSON-safe data (no custom objects left).
    import json

    json.dumps(serialized)  # raises if anything isn't JSON-serializable


def test_load_messages_restores_conversation_state():
    agent = SupportAgent.__new__(SupportAgent)
    agent.messages = []

    saved = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "text", "text": "Hello! How can I help?"}]},
    ]
    agent.load_messages(saved)

    assert agent.messages == saved


def test_save_and_load_round_trip_is_stable():
    """to_serializable_messages() -> load_messages() -> to_serializable_messages()
    again should be idempotent (nothing lost or mangled on a second pass)."""
    agent = SupportAgent.__new__(SupportAgent)
    agent.messages = [
        {"role": "user", "content": "Do you ship internationally?"},
        {"role": "assistant", "content": [FakePydanticBlock(type="text", text="We ship within Australia only.")]},
    ]

    first_pass = agent.to_serializable_messages()

    resumed_agent = SupportAgent.__new__(SupportAgent)
    resumed_agent.messages = []
    resumed_agent.load_messages(first_pass)
    second_pass = resumed_agent.to_serializable_messages()

    assert first_pass == second_pass
