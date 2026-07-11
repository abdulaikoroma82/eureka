"""Variable naming engine.

Purpose
-------
Turn human question text into professional XLSForm variable names that are
lowercase, underscore-separated, meaningful, free of spaces and unique
within a form.

Inputs
------
* A question label (``str``).
* A set of names already used (so duplicates get a numeric suffix).

Outputs
-------
A safe, unique identifier (``str``).

Examples
--------
>>> gen = VariableGenerator()
>>> gen.generate("Child age in months")
'child_age_months'
>>> gen.generate("Preferred contact method")
'preferred_contact_method'
>>> gen.generate("Child age in months")   # duplicate -> suffixed
'child_age_months_2'
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

from .knowledge_base import KnowledgeBase

# XLSForm identifiers must start with a letter/underscore and contain only
# letters, digits and underscores.
_NON_WORD = re.compile(r"[^0-9a-zA-Z]+")
_MULTI_UNDERSCORE = re.compile(r"_+")


class VariableGenerator:
    """Deterministically derive unique variable names."""

    def __init__(self, knowledge: Optional[KnowledgeBase] = None) -> None:
        self.kb = knowledge or KnowledgeBase.load()
        naming = self.kb.naming_rules()
        self.max_length: int = int(naming.get("max_length", 40))
        self.stopwords: Set[str] = set(naming.get("stopwords", []))
        self.abbreviations: Dict[str, str] = dict(naming.get("abbreviations", {}))
        self._used: Set[str] = set()

    # ------------------------------------------------------------------
    def reset(self) -> None:
        """Forget previously issued names (start a fresh form)."""
        self._used.clear()

    def register(self, name: str) -> None:
        """Mark *name* as already taken (e.g. explicit names from input)."""
        if name:
            self._used.add(name)

    # ------------------------------------------------------------------
    def _slugify(self, text: str) -> str:
        text = text.strip().lower()
        # Replace common symbols with words before stripping.
        text = text.replace("%", " percent ").replace("#", " number ")
        text = text.replace("&", " and ")
        tokens = [t for t in _NON_WORD.split(text) if t]

        # Drop stopwords but keep at least one meaningful token.
        meaningful = [t for t in tokens if t not in self.stopwords]
        if not meaningful:
            meaningful = tokens
        # Apply domain abbreviations.
        meaningful = [self.abbreviations.get(t, t) for t in meaningful]

        slug = "_".join(meaningful)
        slug = _MULTI_UNDERSCORE.sub("_", slug).strip("_")

        # Identifiers cannot start with a digit.
        if slug and slug[0].isdigit():
            slug = "q_" + slug
        if not slug:
            slug = "question"

        # Respect the max length without cutting a token in half where avoidable.
        if len(slug) > self.max_length:
            slug = self._truncate_on_boundary(slug, self.max_length)
        return slug

    def _truncate_on_boundary(self, slug: str, limit: int) -> str:
        if len(slug) <= limit:
            return slug
        parts = slug.split("_")
        out: List[str] = []
        length = 0
        for part in parts:
            add = len(part) + (1 if out else 0)
            if length + add > limit:
                break
            out.append(part)
            length += add
        result = "_".join(out) if out else slug[:limit]
        return result.strip("_") or slug[:limit]

    # ------------------------------------------------------------------
    def generate(self, label: str, preferred: Optional[str] = None) -> str:
        """Return a unique variable name for *label*.

        If *preferred* is supplied (an explicit name from the input) it is
        sanitised and used as the base instead of the label.
        """
        base = self._slugify(preferred) if preferred else self._slugify(label)
        name = base
        counter = 2
        while name in self._used:
            suffix = f"_{counter}"
            trimmed = self._truncate_on_boundary(base, self.max_length - len(suffix))
            name = f"{trimmed}{suffix}"
            counter += 1
        self._used.add(name)
        return name
