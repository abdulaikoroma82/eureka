"""Logic engine (Module 5).

Purpose
-------
Translate natural-language skip / relevance instructions into XLSForm
``relevant`` expressions, and decide ``required`` conditions.

Supported patterns (deterministic)
-----------------------------------
* "if yes" / "ask ... if yes"        -> ``${prev}='1'``  (prev is yes_no)
* "if no"                            -> ``${prev}='0'``
* "if child is under 5 years"        -> ``${age}<60`` (months) / ``<5`` (years)
* "if X = value" / "if X is value"   -> ``${x}='value'``
                                        (``selected(${x},'value')`` when x is
                                        a select_multiple)
* comparisons: "if age is at least 18", "if income over 500",
  "if weight <= 20"                  -> ``${age}>=18`` etc.
* compound: "if yes and age over 18",
  "if under 5 years or oedema is yes" -> parts joined with ``and`` / ``or``

"Skip to question N" patterns cannot be inverted safely (XLSForm puts the
condition on the questions being *shown*, not a jump instruction), so they
are surfaced as an explicit review note rather than guessed.

Inputs
------
* The current :class:`~xlsform_architect.models.Question`.
* The *previous* question (used to resolve bare "if yes" references).
* The list of known questions, for cross references.

Outputs
-------
Sets ``question.relevant`` (in place) and returns it.  Unresolvable logic is
preserved verbatim as an assumption so nothing is silently dropped.

Example
-------
>>> from xlsform_architect.models import Question
>>> prev = Question(name="enrolled", xlsform_type="select_one yes_no")
>>> q = Question(raw_label="Admission date", logic="ask if yes")
>>> LogicEngine().resolve(q, previous=prev)
"${enrolled}='1'"
"""

from __future__ import annotations

import re
from typing import List, Optional

from ..models import Question
from .knowledge_base import KnowledgeBase

_NUM = r"(\d+(?:\.\d+)?)"

# Word / symbol comparison operators -> XLSForm operators.
_OP_PATTERNS: List[tuple] = [
    (r">=|=>|at least|no less than|minimum of", ">="),
    (r"<=|=<|at most|no more than|maximum of", "<="),
    (r">|over|more than|above|older than|greater than|exceeds", ">"),
    (r"<|under|less than|below|younger than|fewer than", "<"),
]

_SKIP_TO = re.compile(r"\bskip\s+to\b", re.IGNORECASE)


class LogicEngine:
    """Compile natural-language logic to XLSForm expressions."""

    def __init__(self, knowledge: Optional[KnowledgeBase] = None) -> None:
        self.kb = knowledge or KnowledgeBase.load()
        tokens = self.kb.logic_tokens()
        self.affirmative = [t.lower() for t in tokens.get("affirmative", [])]
        self.negative = [t.lower() for t in tokens.get("negative", [])]

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

        if _SKIP_TO.search(logic):
            question.add_assumption(
                f"Skip pattern detected ('{logic}'). XLSForm expresses skips "
                "as 'relevant' conditions on the questions being shown, not "
                "as jumps - please add the condition to the skipped-to "
                "questions and review.")
            return ""

        expr = self._compile(logic, previous, known or [])
        if expr:
            question.relevant = expr
            question.add_assumption(f"Relevant compiled from logic: '{logic}'.")
        else:
            question.add_assumption(
                f"Logic '{logic}' could not be auto-compiled; please review "
                f"the relevant column.")
        return question.relevant

    # ------------------------------------------------------------------
    def _compile(self, logic: str, previous: Optional[Question],
                 known: List[Question]) -> str:
        """Compile *logic*, handling compound and/or conditions."""
        # Split into atoms on standalone and/or (case-insensitive), keeping
        # the connectives so they can be re-joined in order.
        parts = re.split(r"\s+\b(and|or)\b\s+", logic, flags=re.IGNORECASE)
        if len(parts) > 1:
            exprs: List[str] = []
            for i in range(0, len(parts), 2):
                atom = self._compile_atom(parts[i], previous, known)
                if not atom:
                    return ""      # one uncompilable atom -> honest failure
                exprs.append(atom)
            joined = exprs[0]
            for i in range(1, len(parts), 2):
                connective = parts[i].lower()
                joined += f" {connective} {exprs[(i + 1) // 2]}"
            return joined
        return self._compile_atom(logic, previous, known)

    # ------------------------------------------------------------------
    def _compile_atom(self, atom: str, previous: Optional[Question],
                      known: List[Question]) -> str:
        atom = atom.strip().strip(".,;")
        low = atom.lower()

        # --- bare yes / no ------------------------------------------------
        # Binds to the previous question when it is a yes/no; otherwise to
        # the nearest preceding yes/no question (so "if yes and age over 18"
        # attaches 'yes' to the yes/no even when an age question intervenes).
        if self._is_bare(low, self.affirmative) or self._is_bare(low, self.negative):
            target = self._nearest_yes_no(previous, known)
            if target is not None:
                value = (self._truthy_value(target)
                         if self._is_bare(low, self.affirmative)
                         else self._falsy_value(target))
                return f"${{{target.name}}}={value}"

        # --- numeric comparison ("age is at least 18", "under 5 years") --
        cmp_expr = self._compile_comparison(low, known)
        if cmp_expr:
            return cmp_expr

        # --- "X = value" / "X is value" ----------------------------------
        eq = self._compile_equality(atom, known)
        if eq:
            return eq

        return ""

    # ------------------------------------------------------------------
    def _compile_comparison(self, low: str, known: List[Question]) -> str:
        for pattern, op in _OP_PATTERNS:
            m = re.search(rf"(?:if\s+)?(.*?)\s*(?:is\s+)?(?:{pattern})\s+{_NUM}"
                          rf"\s*(years?|months?)?\s*$", low)
            if not m:
                continue
            subject = m.group(1).strip()
            value = float(m.group(2))
            unit = (m.group(3) or "").rstrip("s")

            q = self._find_question(known, subject.split() or ["age"])
            if q is None and ("year" in low or "month" in low or "age" in low):
                q = self._find_question(known, ["age", "months", "years"])
            if q is None:
                return ""
            var = q.name
            # Convert years to months when the target field is in months.
            if unit == "year" and "month" in var:
                value *= 12
            return f"${{{var}}}{op}{self._fmt(value)}"
        return ""

    def _compile_equality(self, atom: str, known: List[Question]) -> str:
        m = re.search(r"(?:if\s+)?(.+?)\s*(?:=|==|\bis\b|\bequals\b)\s*(.+)",
                      atom, re.IGNORECASE)
        if not m:
            return ""
        subject = m.group(1).strip()
        value = m.group(2).strip().strip(".,;").strip("'\"")
        q = self._find_question(known, subject.lower().split())
        if q is None:
            return ""
        var = q.name
        if re.fullmatch(_NUM, value):
            return f"${{{var}}}={value}"
        value_slug = value.lower().replace(" ", "_")
        # Yes/No answers are stored as 1/0 in the shared yes_no list.
        if "yes_no" in (q.xlsform_type or ""):
            if value.lower() in ("yes", "true"):
                return f"${{{var}}}='1'"
            if value.lower() in ("no", "false"):
                return f"${{{var}}}='0'"
        if q.base_type == "select_multiple":
            return f"selected(${{{var}}}, '{value_slug}')"
        return f"${{{var}}}='{value_slug}'"

    # ------------------------------------------------------------------
    @staticmethod
    def _nearest_yes_no(previous: Optional[Question],
                        known: List[Question]) -> Optional[Question]:
        """The question a bare yes/no condition refers to.

        Prefers the immediately preceding question when it is a yes/no;
        otherwise the last yes/no *before* the previous question in document
        order; finally falls back to the previous question itself.
        """
        def is_yes_no(q: Optional[Question]) -> bool:
            return q is not None and "yes_no" in (q.xlsform_type or "")

        if is_yes_no(previous):
            return previous
        if previous is not None and known:
            try:
                cut = known.index(previous) + 1
            except ValueError:
                cut = len(known)
            for q in reversed(known[:cut]):
                if is_yes_no(q):
                    return q
        return previous

    def _truthy_value(self, question: Question) -> str:
        return "'1'" if "yes_no" in (question.xlsform_type or "") else "'yes'"

    def _falsy_value(self, question: Question) -> str:
        return "'0'" if "yes_no" in (question.xlsform_type or "") else "'no'"

    def _find_question(self, known: List[Question],
                       keywords: List[str]) -> Optional[Question]:
        """Best-match question whose name/label mentions the keywords."""
        keywords = [k for k in keywords
                    if k and k not in ("if", "the", "a", "an", "is", "are")]
        if not keywords:
            return None
        best, best_score = None, 0
        for q in known:
            if q.is_structural or not q.name:
                continue
            hay = f"{q.name} {q.raw_label}".lower()
            score = sum(1 for kw in keywords if kw in hay)
            if score > best_score:
                best, best_score = q, score
        return best

    @staticmethod
    def _is_bare(text: str, tokens: List[str]) -> bool:
        """True when *text* is essentially just an (if-)yes/no token."""
        stripped = re.sub(r"^\s*(if|ask if|only if|when)\s+", "", text).strip()
        return stripped in tokens or text.strip() in tokens

    @staticmethod
    def _fmt(value: float) -> str:
        return str(int(value)) if value == int(value) else str(value)
