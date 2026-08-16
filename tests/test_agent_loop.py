"""
Tests the SupportAgent tool-use loop mechanics WITHOUT calling the real
Anthropic API — a fake client stands in for anthropic.Anthropic and returns
scripted responses (a tool_use turn followed by a text turn), so we can
verify: message history accumulation, tool dispatch to the real mock
backend, tool_result formatting, and final text extraction.

Run with: pytest tests/test_agent_loop.py -v
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent import SupportAgent


class FakeContentBlock:
    def __init__(self, type_, **kwargs):
        self.type = type_
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeResponse:
    def __init__(self, content, stop_reason):
        self.content = content
        self.stop_reason = stop_reason


class FakeMessagesAPI:
    """Returns a pre-scripted sequence of responses, one per .create() call."""

    def __init__(self, scripted_responses):
        self._responses = list(scripted_responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, scripted_responses):
        self.messages = FakeMessagesAPI(scripted_responses)


def test_agent_loop_dispatches_tool_and_returns_final_text():
    tool_use_response = FakeResponse(
        content=[
            FakeContentBlock(
                "tool_use",
                id="toolu_1",
                name="get_order_status",
                input={"order_id": "BK-10021", "customer_email": "jane.doe@example.com"},
            )
        ],
        stop_reason="tool_use",
    )
    final_response = FakeResponse(
        content=[FakeContentBlock("text", text="Your order BK-10021 was delivered on Aug 9.")],
        stop_reason="end_turn",
    )

    fake_client = FakeClient([tool_use_response, final_response])
    agent = SupportAgent(client=fake_client, model="fake-model")

    reply = agent.send("Where's my order BK-10021? My email is jane.doe@example.com")

    assert reply == "Your order BK-10021 was delivered on Aug 9."
    assert len(agent.tool_call_log) == 1
    assert agent.tool_call_log[0]["tool"] == "get_order_status"
    assert agent.tool_call_log[0]["result"]["order"]["order_id"] == "BK-10021"

    # Two API calls: one that returned tool_use, one that returned final text
    assert len(fake_client.messages.calls) == 2
    # Message history should include user msg, assistant tool_use msg,
    # user tool_result msg, assistant final text msg
    assert len(agent.messages) == 4
    assert agent.messages[0]["role"] == "user"
    assert agent.messages[2]["content"][0]["type"] == "tool_result"


def test_agent_loop_no_tool_use_returns_text_directly():
    response = FakeResponse(
        content=[FakeContentBlock("text", text="We ship within Australia only, 3-5 business days.")],
        stop_reason="end_turn",
    )
    fake_client = FakeClient([response])
    agent = SupportAgent(client=fake_client, model="fake-model")

    reply = agent.send("Do you ship internationally?")

    assert "3-5 business days" in reply
    assert len(agent.tool_call_log) == 0
    assert len(fake_client.messages.calls) == 1


def test_agent_loop_handles_unknown_tool_gracefully():
    tool_use_response = FakeResponse(
        content=[FakeContentBlock("tool_use", id="toolu_x", name="not_a_real_tool", input={})],
        stop_reason="tool_use",
    )
    final_response = FakeResponse(
        content=[FakeContentBlock("text", text="Let me get a human to help with that.")],
        stop_reason="end_turn",
    )
    fake_client = FakeClient([tool_use_response, final_response])
    agent = SupportAgent(client=fake_client, model="fake-model")

    reply = agent.send("do something weird")

    assert reply == "Let me get a human to help with that."
    assert agent.tool_call_log[0]["result"]["error"] == "unknown_tool"


def test_agent_loop_gives_up_after_max_iterations():
    # Every call returns tool_use, never resolving -> loop should bail out
    # gracefully instead of looping forever or crashing.
    tool_use_response = FakeResponse(
        content=[
            FakeContentBlock(
                "tool_use", id="toolu_loop", name="search_policy_kb", input={"query": "shipping"}
            )
        ],
        stop_reason="tool_use",
    )
    fake_client = FakeClient([tool_use_response] * 3)
    agent = SupportAgent(client=fake_client, model="fake-model")

    reply = agent.send("test", max_tool_iterations=3)

    assert "team member" in reply.lower()
    assert len(fake_client.messages.calls) == 3
