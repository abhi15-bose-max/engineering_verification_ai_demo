"""Turns a free-text ODE task ("Solve y'(x)+y(x)=0 with y(0)=2.") into a
structured equation + condition list the symbolic verifier can use.

This is intentionally a small, deterministic splitter, not an NL model -
the platform's job is to demonstrate verified generation, not to be a
general-purpose math NLU system. It covers the demo's example shape well
and fails loudly (ValueError) rather than guessing silently.
"""
from __future__ import annotations

import re

_SPLIT_WORDS = re.compile(r"\b(with|given|where)\b", re.IGNORECASE)
_LEAD_WORDS = re.compile(r"^\s*(solve|find\s+y\s+such\s+that\s*:?|solve\s+for\s+y\s*:?)\s*", re.IGNORECASE)


def split_equation_and_conditions(task_text: str) -> tuple[str, list[str]]:
    text = task_text.strip().rstrip(".")
    text = _LEAD_WORDS.sub("", text).strip()

    parts = _SPLIT_WORDS.split(text)
    equation_part = parts[0].strip()
    rest = "".join(parts[1:]) if len(parts) > 1 else ""
    # parts alternates [text, splitword, text, splitword, text...]; rebuild the
    # remainder by dropping the matched keywords themselves.
    remainder_chunks = parts[2::2] if len(parts) > 2 else ([parts[-1]] if len(parts) > 1 else [])
    remainder = " ".join(remainder_chunks).strip()

    if not equation_part:
        raise ValueError("Could not find an equation in the task text.")

    conditions: list[str] = []
    if remainder:
        for chunk in re.split(r",|;|\band\b", remainder, flags=re.IGNORECASE):
            chunk = chunk.strip().strip(".")
            if chunk:
                conditions.append(chunk)

    return equation_part, conditions
