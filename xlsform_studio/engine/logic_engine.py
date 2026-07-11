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
* The current :class:`~xlsform_studio.models.Question`.
* The *previous* question (used to resolve bare "if yes" references).
* The list of known questions, for cross references.

Outputs
-------
Sets ``question.relevant`` (in place) and returns it.  Unresolvable logic is
preserved verbatim as an assumption so nothing is silently dropped.

Example
-------
>>> from xlsform_studio.models import Question
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
        # Protect the "and" inside "between A and B" from the compound split.
        protected = re.sub(rf"\b(between\s+{_NUM})\s+and\s+({_NUM})",
                           r"\1 ~AND~ \3", logic, flags=re.IGNORECASE)
        # Split into atoms on standalone and/or (case-insensitive), keeping
        # the connectives so they can be re-joined in order.
        parts = re.split(r"\s+\b(and|or)\b\s+", protected, flags=re.IGNORECASE)
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
        return self._compile_atom(protected, previous, known)

    # ------------------------------------------------------------------
    #: Leading connective words stripped from every atom before matching.
    _ATOM_PREFIX = re.compile(
        r"^\s*(?:ask\s+)?(?:only\s+if|if|when|where|provided(?:\s+that)?)\s+",
        re.IGNORECASE)
    _UNLESS = re.compile(r"^\s*(?:ask\s+)?unless\s+", re.IGNORECASE)
    _NOT_PREFIX = re.compile(r"^\s*not\s+", re.IGNORECASE)
    #: "question 3" / "Q3" references to a numbered source question.
    _QREF = re.compile(r"^(?:question|q)\s*\.?\s*(\d{1,3})$", re.IGNORECASE)

    def _compile_atom(self, atom: str, previous: Optional[Question],
                      known: List[Question]) -> str:
        atom = atom.strip().strip(".,;")

        # --- "unless X" -> not(X) ---------------------------------------
        m = self._UNLESS.match(atom)
        if m:
            inner = self._compile_atom(atom[m.end():], previous, known)
            return f"not({inner})" if inner else ""

        # Strip a leading if/only if/when/where connective.
        atom = self._ATOM_PREFIX.sub("", atom).strip()

        # --- "not X" -> not(X) --------------------------------------------
        m = self._NOT_PREFIX.match(atom)
        if m:
            remainder = atom[m.end():]
            # "not yes"/"not no" reads naturally as the opposite bare answer.
            inner = self._compile_atom(remainder, previous, known)
            return f"not({inner})" if inner else ""

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

        # --- "X between A and B" (the ~AND~ placeholder from _compile) ---
        between = self._compile_between(low, known)
        if between:
            return between

        # --- numeric comparison ("age is at least 18", "under 5 years") --
        cmp_expr = self._compile_comparison(low, known)
        if cmp_expr:
            return cmp_expr

        # --- "X is not value" -> != ---------------------------------------
        neq = self._compile_inequality(atom, known)
        if neq:
            return neq

        # --- "X = value" / "X is value" ----------------------------------
        eq = self._compile_equality(atom, known)
        if eq:
            return eq

        # --- bare choice value: "if married" -------------------------------
        shorthand = self._compile_choice_shorthand(low, known)
        if shorthand:
            return shorthand

        return ""

    # ------------------------------------------------------------------
    def _compile_between(self, low: str, known: List[Question]) -> str:
        # The ~AND~ placeholder was inserted pre-lowercasing; match either case.
        m = re.search(rf"(.*?)\s*(?:is\s+)?between\s+{_NUM}\s+~and~\s+{_NUM}"
                      rf"\s*(years?|months?)?\s*$", low, re.IGNORECASE)
        if not m:
            return ""
        subject = m.group(1).strip()
        lo, hi = float(m.group(2)), float(m.group(3))
        q = self._resolve_subject(subject, known)
        if q is None:
            return ""
        var = q.name
        unit = (m.group(4) or "").rstrip("s")
        if unit == "year" and "month" in var:
            lo, hi = lo * 12, hi * 12
        return (f"${{{var}}}>={self._fmt(lo)} and "
                f"${{{var}}}<={self._fmt(hi)}")

    def _compile_inequality(self, atom: str, known: List[Question]) -> str:
        m = re.search(r"(.+?)\s+(?:is\s+not|!=|is\s+different\s+from|"
                      r"does\s+not\s+equal)\s+(.+)", atom, re.IGNORECASE)
        if not m:
            return ""
        eq = self._compile_equality(f"{m.group(1)} is {m.group(2)}", known)
        if not eq:
            return ""
        # Flip the operator the equality compiler produced.
        if eq.startswith("selected("):
            return f"not({eq})"
        return eq.replace("=", "!=", 1)

    def _compile_choice_shorthand(self, low: str, known: List[Question]) -> str:
        """Resolve a bare option mention: "if married" -> ${marital}='married'.

        Only fires when exactly ONE select question offers the value, so an
        ambiguous mention stays honestly uncompiled.
        """
        slug = low.strip().replace(" ", "_")
        if not slug or not re.fullmatch(r"[a-z0-9_]{2,40}", slug):
            return ""
        holders = []
        for q in known:
            if not q.references_choices or not q.name:
                continue
            for choice in q.raw_choices:
                cslug = str(choice).strip().lower().replace(" ", "_")
                if cslug == slug or cslug == f"{slug}={slug}":
                    holders.append((q, slug))
                    break
                # coded options ("m=Married") match on the label
                if "=" in str(choice):
                    code, _, label = str(choice).partition("=")
                    if label.strip().lower().replace(" ", "_") == slug:
                        holders.append((q, code.strip().lower()))
                        break
        if len(holders) != 1:
            return ""
        q, value = holders[0]
        if q.base_type == "select_multiple":
            return f"selected(${{{q.name}}}, '{value}')"
        return f"${{{q.name}}}='{value}'"

    def _resolve_subject(self, subject: str,
                         known: List[Question]) -> Optional[Question]:
        """Find the question a subject phrase refers to.

        Handles "question 3"/"Q3" numbered references (via the source
        number captured by the parser) before falling back to keyword match.
        """
        m = self._QREF.match(subject.strip())
        if m:
            number = m.group(1)
            for q in known:
                if q.source_number == number:
                    return q
            return None
        return self._find_question(known, subject.lower().split() or ["age"])

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

            q = self._resolve_subject(subject, known)
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
        value = m.group(2).strip()
        # Trim instruction continuations: "yes, ask question 3" -> "yes",
        # "married then continue" -> "married".
        value = re.split(r",|\bthen\b|\bask\b|\bgo\s+to\b|\bcontinue\b",
                         value, 1)[0].strip()
        value = value.strip(".,;").strip("'\"")
        if not value:
            return ""
        q = self._resolve_subject(subject, known)
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
        # Coded options ("2=Married") store the code, not the label - map
        # the human wording back to the stored value.
        stored = self._choice_value_for(q, value_slug)
        if q.base_type == "select_multiple":
            return f"selected(${{{var}}}, '{stored}')"
        return f"${{{var}}}='{stored}'"

    @staticmethod
    def _choice_value_for(q: Question, value_slug: str) -> str:
        """The stored choice name a human-written value refers to."""
        for choice in q.raw_choices:
            text = str(choice)
            if "=" in text:
                code, _, label = text.partition("=")
                if label.strip().lower().replace(" ", "_") == value_slug:
                    return code.strip()
            elif text.strip().lower().replace(" ", "_") == value_slug:
                return value_slug
        return value_slug

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
        """True when *text* is essentially just an (if-)yes/no token.

        Also recognises common answer-phrasings: "the answer is yes",
        "response is no", "they answer yes", "answered yes".
        """
        stripped = re.sub(r"^\s*(if|ask if|only if|when)\s+", "", text).strip()
        stripped = re.sub(r"^(?:the\s+)?(?:answer|response)\s+is\s+", "",
                          stripped).strip()
        stripped = re.sub(r"^they\s+(?:say|answer(?:ed)?)\s+", "", stripped).strip()
        stripped = re.sub(r"^answered\s+", "", stripped).strip()
        return stripped in tokens or text.strip() in tokens

    @staticmethod
    def _fmt(value: float) -> str:
        return str(int(value)) if value == int(value) else str(value)
