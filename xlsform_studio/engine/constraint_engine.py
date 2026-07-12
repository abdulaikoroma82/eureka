"""Constraint engine.

Purpose
-------
Attach validation ``constraint`` expressions and human ``constraint_message``
text to numeric / date questions, using semantic templates from the knowledge
base.

Examples
--------
* age (months)  -> ``. >= 0 and . <= 1200``
* age           -> ``. >= 0 and . <= 120``
* percentage    -> ``. >= 0 and . <= 100``
* date          -> ``. <= today()``

These are the domain-neutral templates bundled in ``xlsform_rules.yaml``;
domain-specific ranges (e.g. a particular weight range) can be added there
without touching this code - see "The rule pack" in the README.

Inputs
------
A :class:`~xlsform_studio.models.Question` whose ``xlsform_type`` has
already been resolved by the classifier.

Outputs
-------
The question with ``constraint`` / ``constraint_message`` populated in place
(only when empty - explicit values from input win).

Example
-------
>>> from xlsform_studio.models import Question
>>> q = Question(raw_label="Respondent age", xlsform_type="integer")
>>> ConstraintEngine().apply(q).constraint
'. >= 0 and . <= 120'
"""

from __future__ import annotations

import re
from typing import Optional

from ..models import Question
from .knowledge_base import KnowledgeBase


class ConstraintEngine:
    """Add deterministic validation constraints."""

    def __init__(self, knowledge: Optional[KnowledgeBase] = None) -> None:
        self.kb = knowledge or KnowledgeBase.load()
        self.templates = self.kb.constraint_templates()
        self.type_constraints = self.kb.type_constraints()

    # ------------------------------------------------------------------
    def apply(self, question: Question) -> Question:
        """Populate ``constraint`` / ``constraint_message`` in place."""
        if question.constraint:  # explicit override wins
            return question

        base_type = question.base_type
        label = (question.raw_label or "").lower()

        # 1. Semantic template match (keyword + applicable type).
        for tpl in self.templates:
            applies = tpl.get("applies_to", [])
            if applies and base_type not in applies:
                continue
            if self._matches(label, tpl.get("match", [])):
                question.constraint = tpl["constraint"]
                question.constraint_message = tpl.get("message", "")
                question.add_decision(
                    "constraint", question.constraint, "medium",
                    f"Constraint applied from template match ({', '.join(tpl['match'])})."
                )
                return question

        # 2. Generic per-type constraint (e.g. dates not in the future).
        generic = self.type_constraints.get(base_type)
        if generic:
            question.constraint = generic["constraint"]
            question.constraint_message = generic.get("message", "")
            question.add_decision("constraint", question.constraint, "low",
                                  f"Default '{base_type}' constraint applied.")
        return question

    # ------------------------------------------------------------------
    @staticmethod
    def _matches(label: str, keywords) -> bool:
        for kw in keywords:
            if not kw:
                continue
            kw = kw.lower()
            # Short alphabetic keywords (e.g. "age") use word boundaries so
            # they do not match inside longer words ("percentage").
            if kw.isalpha() and len(kw) <= 4:
                if re.search(rf"\b{re.escape(kw)}\b", label):
                    return True
            elif kw in label:
                return True
        return False
