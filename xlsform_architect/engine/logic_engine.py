"""Logic engine (Module 5).

Purpose
-------
Translate natural-language skip / relevance instructions into XLSForm
``relevant`` expressions, and decide ``required`` conditions.

Supported patterns (deterministic)
-----------------------------------
* "if yes"                     -> ``${prev}='1'``  (when prev is yes_no)
* "ask ... if yes"             -> ``${prev}='1'``
* "if no"                      -> ``${prev}='0'``
* "if child is under 5 years"  -> ``${age}<60`` (months) / ``<5`` (years)
* "if X = value"               -> ``${x}='value'``

Inputs
------
* The current :class:`~xlsform_architect.models.Question`.
* The *previous* question (used to resolve bare "if yes" references).
* An optional lookup of variable names by keyword, for cross references.

Outputs
-------
Sets ``question.relevant`` (in place) and returns it.  Unresolvable logic is
preserved verbatim as an assumption so nothing is silently dropped.

Example
-------
>>> from xlsform_architect.models import Question
>>> prev = Question(name="enrolled_otp", xlsform_type="select_one yes_no")
>>> q = Question(raw_label="Admission date", logic="ask if yes")
>>> LogicEngine().resolve(q, previous=prev)
"${enrolled_otp}='1'"
"""

from __future__ import annotations

import re
from typing import List, Optional

from ..models import Question
from .knowledge_base import KnowledgeBase

_NUM = r"(\d+(?:\.\d+)?)"


class LogicEngine:
    """Compile natural-language logic to XLSForm expressions."""

    def __init__(self, knowledge: Optional[KnowledgeBase] = None) -> None:
        self.kb = knowledge or KnowledgeBase.load()
        tokens = self.kb.logic_tokens()
        self.affirmative = [t.lower() for t in tokens.get("affirmative", [])]
        self.negative = [t.lower() for t in tokens.get("negative", [])]
        self.under = [t.lower() for t in tokens.get("under", [])]
        self.over = [t.lower() for t in tokens.get("over", [])]

    # ------------------------------------------------------------------
    def resolve(self, question: Question, previous: Optional[Question] = None,
                known: Optional[List[Question]] = None) -> str:
        """Populate ``question.relevant`` from ``question.logic``.

        An explicit ``relevant`` already on the question is left untouched.
        """
        if question.relevant:
            return question.relevant

        logic = (question.logic or "").strip()
        if not logic:
            return ""

        expr = self._compile(logic, previous, known or [])
        if expr:
            question.relevant = expr
            question.add_assumption(f"Relevant compiled from logic: '{logic}'.")
        else:
            question.add_assumption(
                f"Logic '{logic}' could not be auto-compiled; please review the relevant column."
            )
        return question.relevant

    # ------------------------------------------------------------------
    def _compile(self, logic: str, previous: Optional[Question],
                 known: List[Question]) -> str:
        low = logic.lower()

        # --- yes / no against the previous question ---------------------
        if previous is not None:
            if self._contains_any(low, self.affirmative):
                return f"${{{previous.name}}}={self._truthy_value(previous)}"
            if self._contains_any(low, self.negative):
                return f"${{{previous.name}}}={self._falsy_value(previous)}"

        # --- age comparisons -------------------------------------------
        age_expr = self._compile_age(low, known)
        if age_expr:
            return age_expr

        # --- explicit "X = value" / "X is value" -----------------------
        eq = self._compile_equality(logic, known)
        if eq:
            return eq

        return ""

    # ------------------------------------------------------------------
    def _compile_age(self, low: str, known: List[Question]) -> str:
        age_var = self._find_var(known, ["age", "months", "years"]) or "age"
        # "under 5 years" -> months if the field is in months.
        m = re.search(rf"(?:{'|'.join(map(re.escape, self.under))})\s+{_NUM}\s*(year|month)?", low)
        if m and any(w in low for w in self.under):
            value = float(m.group(1))
            unit = m.group(2) or ("year" if "year" in low else "")
            months = value * 12 if unit == "year" else value
            if "month" in age_var:
                return f"${{{age_var}}}<{int(months)}"
            return f"${{{age_var}}}<{self._fmt(value)}"
        m = re.search(rf"(?:{'|'.join(map(re.escape, self.over))})\s+{_NUM}\s*(year|month)?", low)
        if m and any(w in low for w in self.over):
            value = float(m.group(1))
            unit = m.group(2) or ("year" if "year" in low else "")
            months = value * 12 if unit == "year" else value
            if "month" in age_var:
                return f"${{{age_var}}}>{int(months)}"
            return f"${{{age_var}}}>{self._fmt(value)}"
        return ""

    def _compile_equality(self, logic: str, known: List[Question]) -> str:
        m = re.search(r"if\s+(.+?)\s*(?:=|==|\bis\b|\bequals\b)\s*(.+)", logic, re.IGNORECASE)
        if not m:
            return ""
        subject = m.group(1).strip()
        value = m.group(2).strip().strip(".,;").strip("'\"")
        var = self._find_var(known, subject.lower().split())
        if not var:
            return ""
        if re.fullmatch(_NUM, value):
            return f"${{{var}}}={value}"
        return f"${{{var}}}='{value.lower()}'"

    # ------------------------------------------------------------------
    def _truthy_value(self, question: Question) -> str:
        # yes_no list uses '1'/'0'; fall back to 'yes'.
        return "'1'" if "yes_no" in (question.xlsform_type or "") else "'yes'"

    def _falsy_value(self, question: Question) -> str:
        return "'0'" if "yes_no" in (question.xlsform_type or "") else "'no'"

    def _find_var(self, known: List[Question], keywords: List[str]) -> str:
        for q in known:
            hay = f"{q.name} {q.raw_label}".lower()
            if any(kw and kw in hay for kw in keywords):
                return q.name
        return ""

    @staticmethod
    def _contains_any(text: str, tokens: List[str]) -> bool:
        return any(re.search(rf"\b{re.escape(t)}\b", text) for t in tokens if t)

    @staticmethod
    def _fmt(value: float) -> str:
        return str(int(value)) if value == int(value) else str(value)
