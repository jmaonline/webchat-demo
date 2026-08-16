"""
Quick manual test harness — chat with the agent from the terminal, using
the REAL Anthropic API (requires ANTHROPIC_API_KEY to be set).

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python -m backend.chat_cli

Try prompts like:
    "Hi, can you check on order BK-10021? My email is jane.doe@example.com"
    "I want to return the Project Hail Mary book from that order, it arrived damaged"
    "What's your shipping policy?"
    "I forgot my password, can you help?"
"""
import os
import sys

from .agent import SupportAgent


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Export it first, e.g.:")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    agent = SupportAgent()
    print("Bucky · Bookly Support (Ctrl-C to quit)")
    print("-" * 50)
    try:
        while True:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            reply = agent.send(user_input)
            print(f"Agent: {reply}\n")
            if agent.tool_call_log:
                last = agent.tool_call_log[-1]
                print(f"  [debug: last tool call -> {last['tool']}({last['input']})]\n")
    except (KeyboardInterrupt, EOFError):
        print("\nBye!")


if __name__ == "__main__":
    main()
