"""Deterministic validators for AI output (part of the AI safety layer).

Purpose
-------
Every AI feature follows the same contract: the model may *suggest*, but a
deterministic check decides whether the suggestion is structurally sound
before it is ever shown or applied. This module collects those checks in one
place so each AI feature validates the same way and the tests can exercise
the gates directly, without any model in the loop.

Each function returns ``None`` when the input is acceptable, or a
human-readable error string describing exactly why it was rejected -
callers put that string straight into their "[AI ...] Rejected ..." notes.

Inputs / outputs
----------------
Plain values (lists, strings, expressions); no network, no models, no state.

Example
-------
>>> check_permutation(["a", "b", "c"], ["c", "a", "b"]) is None
True
>>> check_permutation(["a", "b"], ["a", "a"])
"not a permutation of the original options: missing ['b'], added/duplicated ['a']"
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, Iterable, List, Optional, Sequence, Set

from .expression_validator import ExpressionValidator

_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
#: XLSForm-safe identifier: starts with a letter, then letters/digits/underscores.
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

#: The only severities AI review output may carry - advisory levels that can
#: never block deployment the way a real structural ``error`` does.
ADVISORY_LEVELS = ("info", "warning")


# ---------------------------------------------------------------------------
# Coverage / permutation checks (grouping, choice ordering)
# ---------------------------------------------------------------------------
def check_covers_exactly_once(groups: Sequence[Sequence[int]],
                              total: int) -> Optional[str]:
    """Every index ``0..total-1`` must appear in exactly one group."""
    seen = Counter(i for group in groups for i in group)
    bad_type = [i for i in seen if not isinstance(i, int)]
    if bad_type:
        return f"non-integer question indices: {sorted(map(str, bad_type))}"
    out_of_range = sorted(i for i in seen if i < 0 or i >= total)
    if out_of_range:
        return f"question indices out of range: {out_of_range}"
    duplicated = sorted(i for i, n in seen.items() if n > 1)
    if duplicated:
        return f"question indices assigned more than once: {duplicated}"
    missing = sorted(set(range(total)) - set(seen))
    if missing:
        return f"question indices not assigned to any section: {missing}"
    return None


def check_permutation(original: Sequence[str],
                      suggested: Sequence[str]) -> Optional[str]:
    """The suggestion must contain exactly the original items, reordered."""
    orig, sugg = Counter(original), Counter(suggested)
    if orig == sugg:
        return None
    missing = sorted((orig - sugg).keys())
    added = sorted((sugg - orig).keys())
    return (f"not a permutation of the original options: "
            f"missing {missing}, added/duplicated {added}")


def check_unique_nonempty(names: Iterable[str]) -> Optional[str]:
    """Section/list names must be non-empty and unique."""
    names = [str(n).strip() for n in names]
    if any(not n for n in names):
        return "contains an empty name"
    duplicates = sorted(n for n, c in Counter(names).items() if c > 1)
    if duplicates:
        return f"duplicate names: {duplicates}"
    return None


# ---------------------------------------------------------------------------
# Expression checks (constraints, relevant conditions)
# ---------------------------------------------------------------------------
def check_expression(expr: str, valid_names: Set[str]) -> Optional[str]:
    """Syntax-check *expr* and verify every ``${...}`` names a real question."""
    error, _ = ExpressionValidator().check(expr)
    if error:
        return f"expression failed syntax validation ({error})"
    unknown = set(_REF.findall(expr)) - valid_names
    if unknown:
        return f"references unknown field(s) {sorted(unknown)}"
    return None


def check_placeholders_preserved(original: str, suggested: str) -> Optional[str]:
    """A reworded label must keep exactly the ``${...}`` refs of the original."""
    orig, sugg = set(_REF.findall(original)), set(_REF.findall(suggested))
    if orig == sugg:
        return None
    lost, invented = sorted(orig - sugg), sorted(sugg - orig)
    parts = []
    if lost:
        parts.append(f"drops placeholder(s) {lost}")
    if invented:
        parts.append(f"introduces placeholder(s) {invented}")
    return " and ".join(parts)


# ---------------------------------------------------------------------------
# Name / severity checks (naming suggestions, review findings)
# ---------------------------------------------------------------------------
def check_variable_name(name: str, existing: Set[str],
                        max_length: int = 40) -> Optional[str]:
    """Platform rules: starts with a letter, identifier chars only, unique,
    within the safe length limit."""
    if not name:
        return "empty name"
    if not _NAME.match(name):
        return ("not a valid identifier (must start with a letter and use "
                "only letters, digits and underscores)")
    if len(name) > max_length:
        return f"longer than the {max_length}-character platform limit"
    if name in existing:
        return "collides with an existing question name"
    return None


def clamp_advisory_level(level: str) -> str:
    """AI findings may only ever be ``info`` or ``warning`` - never error."""
    return level if level in ADVISORY_LEVELS else "warning"
