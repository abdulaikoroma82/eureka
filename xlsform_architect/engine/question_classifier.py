"""Question classification engine (Module 2).

Purpose
-------
Determine the correct XLSForm ``type`` for each question using deterministic
keyword rules from the knowledge base plus the shape of the extracted answer
options.

Rules (summary)
---------------
* Yes/No options            -> ``select_one yes_no``
* Several options, one pick  -> ``select_one <list>``
* Several options, many picks -> ``select_multiple <list>``
* "age", "how many"          -> ``integer``
* "weight", "amount"         -> ``decimal``
* "date"                     -> ``date``
* "gps"                      -> ``geopoint``
* "photo"                    -> ``image``

Inputs
------
A :class:`~xlsform_architect.models.Question` (with ``raw_label`` and
optionally ``raw_choices`` / ``xlsform_type``).

Outputs
-------
The same question, mutated in place with ``xlsform_type`` (and ``list_name``
for selects) resolved, plus an assumption note explaining the decision.

Example
-------
>>> from xlsform_architect.models import Question
>>> c = QuestionClassifier()
>>> q = Question(raw_label="Is the child enrolled in OTP?", raw_choices=["Yes", "No"])
>>> c.classify(q).xlsform_type
'select_one yes_no'
"""

from __future__ import annotations

import re
from typing import List, Optional

from ..models import Question
from .knowledge_base import KnowledgeBase

# Cues that a select question accepts more than one answer.
_MULTI_CUES = [
    "select all", "select all that apply", "check all", "mark all",
    "multiple answers", "all that apply", "tick all",
]


class QuestionClassifier:
    """Assign XLSForm types deterministically."""

    def __init__(self, knowledge: Optional[KnowledgeBase] = None) -> None:
        self.kb = knowledge or KnowledgeBase.load()
        self.yes_no_cfg = self.kb.yes_no()
        self.type_rules = self.kb.type_keywords()

    # ------------------------------------------------------------------
    def classify(self, question: Question, list_name: Optional[str] = None) -> Question:
        """Resolve ``question.xlsform_type`` in place and return it."""
        label = (question.raw_label or "").lower()

        # 1. Respect an already fully-resolved type (e.g. from JSON input),
        #    but still resolve the select list name if it is missing.
        existing = (question.xlsform_type or "").strip()
        if existing and existing not in ("select_one", "select_multiple"):
            return question  # already complete, nothing to infer

        # 2. Questions with answer options are selects.
        if question.raw_choices:
            self._classify_select(question, existing, list_name)
            return question

        # 3. A bare "select_one"/"select_multiple" without options: keep base.
        if existing in ("select_one", "select_multiple") and not question.raw_choices:
            question.add_assumption(
                f"Kept '{existing}' but no answer options were found; add a choice list."
            )
            return question

        # 4. Keyword-driven type detection for non-select questions.
        for rule in self.type_rules:
            if self._matches(label, rule.get("keywords", [])):
                question.xlsform_type = rule["type"]
                question.add_assumption(
                    f"Type '{rule['type']}' inferred from keyword match."
                )
                return question

        # 5. Fallback: free text.
        question.xlsform_type = "text"
        question.add_assumption("No rule matched; defaulted to 'text'.")
        return question

    # ------------------------------------------------------------------
    def _classify_select(self, question: Question, existing: str,
                         list_name: Optional[str]) -> None:
        multi = existing == "select_multiple" or self._looks_multi(question.raw_label)
        base = "select_multiple" if multi else "select_one"

        if self._is_yes_no(question.raw_choices):
            question.xlsform_type = f"select_one {self.yes_no_cfg.get('list_name', 'yes_no')}"
            question.list_name = self.yes_no_cfg.get("list_name", "yes_no")
            question.add_assumption("Yes/No options detected; used shared 'yes_no' list.")
            return

        resolved_list = list_name or question.list_name or "list_placeholder"
        question.list_name = resolved_list
        question.xlsform_type = f"{base} {resolved_list}"
        if multi and existing != "select_multiple":
            question.add_assumption("Wording implies multiple answers; used select_multiple.")

    # ------------------------------------------------------------------
    def _matches(self, label: str, keywords: List[str]) -> bool:
        for kw in keywords:
            kw = kw.lower().strip()
            if not kw:
                continue
            # Word-boundary match for short alphabetic keywords to avoid
            # false hits (e.g. "age" inside "message").
            if kw.isalpha() and len(kw) <= 4:
                if re.search(rf"\b{re.escape(kw)}\b", label):
                    return True
            elif kw in label:
                return True
        return False

    def _looks_multi(self, label: str) -> bool:
        low = (label or "").lower()
        return any(cue in low for cue in _MULTI_CUES)

    def _is_yes_no(self, choices: List[str]) -> bool:
        if len(choices) != 2:
            return False
        pos = {t.lower() for t in self.yes_no_cfg.get("positive_tokens", [])}
        neg = {t.lower() for t in self.yes_no_cfg.get("negative_tokens", [])}
        normalised = {c.strip().lower() for c in choices}
        return bool(normalised & pos) and bool(normalised & neg)
