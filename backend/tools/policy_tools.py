"""
Policy / FAQ knowledge base search. Mock implementation uses simple
keyword overlap scoring against a small markdown file of Q/A entries.

Swap point for a real system: replace `search_policy_kb`'s body with a
call to your real help-center search API or a vector-search/RAG index over
your actual policy documents. Keep the same input/output contract.
"""
from __future__ import annotations

import re
from pathlib import Path

_KB_PATH = Path(__file__).resolve().parent.parent / "mock_data" / "policy_kb.md"

_STOPWORDS = {
    "the", "a", "an", "is", "are", "do", "does", "how", "what", "i", "my",
    "to", "for", "of", "and", "or", "in", "on", "can", "you", "your", "it",
    "me", "please", "with", "about",
}


def _load_entries() -> list[dict]:
    text = _KB_PATH.read_text()
    entries = []
    blocks = re.split(r"\n## Q: ", text)
    for block in blocks[1:]:
        question, _, rest = block.partition("\n")
        answer = rest.replace("A: ", "", 1).strip()
        entries.append({"question": question.strip(), "answer": answer})
    return entries


_ENTRIES = _load_entries()


def _tokenize(s: str) -> set[str]:
    words = re.findall(r"[a-z']+", s.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def search_policy_kb(query: str, max_results: int = 2) -> dict:
    """
    Search the shipping/returns/general-policy FAQ knowledge base.

    Args:
        query: The customer's question or topic, in natural language.
        max_results: Max number of matching entries to return (default 2).

    Returns:
        dict with a list of matching {question, answer} entries, ranked by
        relevance. Empty list if nothing matches well enough.
    """
    query_tokens = _tokenize(query)
    scored = []
    for entry in _ENTRIES:
        entry_tokens = _tokenize(entry["question"]) | _tokenize(entry["answer"])
        overlap = len(query_tokens & entry_tokens)
        if overlap > 0:
            scored.append((overlap, entry))
    scored.sort(key=lambda x: x[0], reverse=True)
    results = [entry for _, entry in scored[:max_results]]
    return {"results": results, "found": len(results) > 0}
