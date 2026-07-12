"""Reviewable parsing: turn every heuristic decision into an editable row.

Purpose
-------
The rule engine makes four kinds of judgment call per question - type,
choice list, ``relevant``, ``constraint`` - each recorded as a structured
:class:`~xlsform_studio.models.Decision` with a confidence
(high/medium/low). Ambiguity the engine could not resolve at all (an
uncompilable skip condition, a "skip to question N" jump) is preserved as
an explicit **low-confidence, blank-value** decision rather than a guessed
expression - the "conservative natural-language compilation" principle:
when unsure, hand it to a human instead of producing something plausible
but wrong.

This module turns those decisions into a flat, reviewable table (one row
per question/field) and applies human edits/approvals back onto the
compiled form. It does not touch the pipeline that produces the
decisions - :mod:`~xlsform_studio.engine.question_classifier`,
:mod:`~xlsform_studio.engine.logic_engine`,
:mod:`~xlsform_studio.engine.constraint_engine`, and their AI-assisted
counterparts - it only reads and (on request) rewrites their output.

Inputs
------
A compiled :class:`~xlsform_studio.models.Questionnaire` (for
:func:`build_review_table`) plus a ``{(question_name, field_name): value}``
edit map (for :func:`apply_review_edits`).

Outputs
-------
:func:`build_review_table` returns :class:`ReviewRow` objects, sorted so
the least-confident and blank ("needs attention") items surface first.
:func:`apply_review_edits` mutates the questionnaire in place and returns
audit-trail notes; every touched field also gets a fresh, high-confidence
"reviewed by a human" :class:`Decision`, so a later export shows the
review happened, not just the machine's original guess.

Example
-------
>>> from xlsform_studio.models import Questionnaire, Question
>>> q = Question(name="age", label="Age", xlsform_type="integer")
>>> q.add_decision("type", "integer", "high", "Type inferred from keyword match.")
>>> rows = build_review_table(Questionnaire(questions=[q]))
>>> rows[0].field_name, rows[0].confidence
('type', 'high')
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from ..models import (DECISION_CONFIDENCE_LEVELS, Decision, Question,
                      Questionnaire)

#: The field-level decision -> Question attribute it edits. "choice_list"
#: is special-cased (it may also need to rewrite the type string's list
#: token) rather than a straight attribute name.
_DIRECT_ATTR = {"relevant": "relevant", "constraint": "constraint"}

_CONFIDENCE_ORDER = {c: i for i, c in enumerate(DECISION_CONFIDENCE_LEVELS)}

FIELD_LABELS: Dict[str, str] = {
    "type": "Question type", "choice_list": "Choice list",
    "relevant": "Relevance", "constraint": "Constraint",
}


@dataclass
class ReviewRow:
    """One editable line in the reviewable-parsing table."""

    question: str          # question variable name
    label: str              # question label, for display
    field_name: str          # "type" | "choice_list" | "relevant" | "constraint"
    value: str              # the field's current (possibly heuristic) value
    confidence: str          # "high" | "medium" | "low"
    reason: str
    #: True when nothing could be inferred at all (e.g. an uncompilable
    #: skip condition) - the conservative-NL case that most needs a human.
    needs_attention: bool = False

    @property
    def field_label(self) -> str:
        return FIELD_LABELS.get(self.field_name, self.field_name)


def build_review_table(questionnaire: Questionnaire) -> List[ReviewRow]:
    """One row per (question, field) - the *latest* decision for each,
    since an AI-assisted pass appends a new decision rather than erasing
    the rule engine's original. Sorted least-confident first."""
    rows: List[ReviewRow] = []
    for q in questionnaire.questions:
        if q.is_structural or not q.name:
            continue
        latest: Dict[str, Decision] = {}
        for d in q.decisions:
            latest[d.field_name] = d
        for field_name, d in latest.items():
            rows.append(ReviewRow(
                question=q.name, label=q.label or q.raw_label,
                field_name=field_name, value=d.value, confidence=d.confidence,
                reason=d.reason, needs_attention=not d.value.strip()))
    rows.sort(key=lambda r: (not r.needs_attention,
                             _CONFIDENCE_ORDER.get(r.confidence, 9),
                             r.question, r.field_name))
    return rows


def apply_review_edits(questionnaire: Questionnaire,
                       edits: Dict[Tuple[str, str], str]) -> List[str]:
    """Apply human-reviewed values back onto the form.

    *edits* maps ``(question_name, field_name) -> value`` - the value the
    reviewer left in place (an implicit approval) or changed (an edit).
    Either way the field is set explicitly and a fresh high-confidence
    Decision is recorded, so the audit trail shows a human signed off.
    """
    notes: List[str] = []
    by_name = {q.name: q for q in questionnaire.questions}
    for (qname, field_name), raw_value in edits.items():
        q = by_name.get(qname)
        if q is None:
            notes.append(f"[Review] '{qname}' no longer exists; the "
                        f"{FIELD_LABELS.get(field_name, field_name)} edit "
                        f"was skipped.")
            continue
        value = (raw_value or "").strip()
        current = _current_value(q, field_name)
        _apply_field(q, field_name, value)
        verb = "approved" if value == current else "edited"
        q.add_decision(field_name, value, "high",
                       f"Reviewed and {verb} by a human.")
        notes.append(f"[Review] '{qname}' {FIELD_LABELS.get(field_name, field_name)} "
                    f"{verb}{': ' + value if verb == 'edited' else ''}.")
    return notes


# ---------------------------------------------------------------------------
def _current_value(q: Question, field_name: str) -> str:
    if field_name == "type":
        return q.xlsform_type
    if field_name == "choice_list":
        return q.choice_list_name
    return getattr(q, _DIRECT_ATTR.get(field_name, field_name), "")


def _apply_field(q: Question, field_name: str, value: str) -> None:
    if field_name == "type":
        q.xlsform_type = value
        parts = value.split()
        if (len(parts) >= 2 and parts[0] in ("select_one", "select_multiple", "rank")
                and parts[1] != "or_other"):
            q.list_name = parts[1]
        return
    if field_name == "choice_list":
        parts = (q.xlsform_type or "").split()
        if len(parts) >= 2 and parts[0] in ("select_one", "select_multiple", "rank"):
            suffix = parts[2:]
            q.xlsform_type = " ".join([parts[0], value, *suffix])
        q.list_name = value
        return
    attr = _DIRECT_ATTR.get(field_name)
    if attr:
        setattr(q, attr, value)
