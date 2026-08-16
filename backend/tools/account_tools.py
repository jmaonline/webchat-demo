"""
Account-related tools. Currently just password reset initiation.

Security note: the reply to the caller is deliberately the same whether or
not the email exists, to avoid account enumeration. The tool result the
agent sees *does* distinguish (so the agent could log/escalate internally
if needed), but the agent's system prompt instructs it to always relay the
neutral message to the customer.
"""
from __future__ import annotations

from . import data_store


def initiate_password_reset(customer_email: str) -> dict:
    """
    Trigger a password reset email for the given account email, if it
    exists. Always relay the neutral "if that email is on file..." message
    to the customer regardless of whether it matched, to avoid revealing
    which emails have accounts.

    Args:
        customer_email: The email address the customer says their account
            uses.

    Returns:
        dict with `matched` (bool, for internal/agent reasoning only) and
        a `customer_message` the agent should relay verbatim.
    """
    matched = data_store.customer_email_exists(customer_email)
    # In a real system: call the auth provider's reset-password API here
    # when matched is True (e.g. Auth0, Cognito, custom auth service).
    return {
        "matched": matched,
        "customer_message": (
            "If that email is on file with us, a password reset link has "
            "been sent — it's valid for 60 minutes. Please check your spam "
            "folder if you don't see it in a few minutes."
        ),
    }
