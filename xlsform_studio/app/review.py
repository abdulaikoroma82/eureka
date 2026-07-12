"""Reviewing the AI draft: make every authored field editable before export.

Purpose
-------
The AI author (:mod:`~xlsform_studio.ai.form_author`) drafts every field of
the form. Four of them - type, choice list, ``relevant``, ``constraint`` -
are also recorded as structured :class:`~xlsform_studio.models.Decision`
entries with a confidence (high/medium/low), so genuine ambiguity surfaces:
anything the author (or the deterministic seam) could not settle is kept as
an explicit **low-confidence, blank-value** decision rather than a guessed
expression - the "conservative compilation" principle: when unsure, hand it
to a human instead of producing something plausible but wrong.

This module exposes two views onto that draft and applies human edits back:

* :func:`build_review_table` - the flat, confidence-sorted table of the four
  decision fields (least-confident / blank first), the "what needs my
  attention" view.
* :func:`build_full_review` - every editable survey-row field grouped by
  question (name, label, hint, required, type, choice list, relevance,
  constraint + message, calculation, choice filter, appearance, default),
  the "let me edit anything" view.

:func:`apply_review_edits` takes a ``{(question_name, field_name): value}``
edit map and writes it back, mutating the questionnaire in place. A renamed
variable has all its ``${...}`` references rewritten across the form; every
touched field gets a fresh, high-confidence "reviewed by a human"
:class:`Decision`, so a later export shows the review happened.

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

import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from ..models import (DECISION_CONFIDENCE_LEVELS, Decision, Question,
                      Questionnaire)
from ..validation.ai_validators import check_variable_name

#: Field name -> Question attribute for straight-through text fields (name,
#: type and choice_list are special-cased in _apply_field / apply_review_edits).
_DIRECT_ATTR = {
    "label": "label", "hint": "hint", "relevant": "relevant",
    "constraint": "constraint", "constraint_message": "constraint_message",
    "calculation": "calculation", "choice_filter": "choice_filter",
    "appearance": "appearance", "default": "default",
}

_CONFIDENCE_ORDER = {c: i for i, c in enumerate(DECISION_CONFIDENCE_LEVELS)}

FIELD_LABELS: Dict[str, str] = {
    "name": "Variable name", "type": "Question type",
    "choice_list": "Choice list", "label": "Label", "hint": "Hint",
    "required": "Required", "relevant": "Relevance", "constraint": "Constraint",
    "constraint_message": "Constraint message", "calculation": "Calculation",
    "choice_filter": "Choice filter", "appearance": "Appearance",
    "default": "Default",
}

#: The decision fields - the ones the AI records a confidence for, and the
#: only ones :func:`build_review_table` (the "needs attention" view) covers.
_DECISION_FIELDS = ("type", "choice_list", "relevant", "constraint")

_MAX_NAME_LENGTH = 40


@dataclass(frozen=True)
class FieldSpec:
    """One editable survey-row field, and how the UI should render it."""

    field_name: str
    #: "text" (one line), "long" (multi-line), or "bool" (checkbox).
    kind: str = "text"
    help: str = ""
    #: Only shown for questions that reference a choice list.
    select_only: bool = False

    @property
    def label(self) -> str:
        return FIELD_LABELS.get(self.field_name, self.field_name)


#: Every editable survey-row field, in a sensible review order.
EDITABLE_FIELD_SPECS: List[FieldSpec] = [
    FieldSpec("name", help="Machine name; all ${references} update automatically."),
    FieldSpec("type", help="e.g. integer, select_one water_sources, calculate."),
    FieldSpec("choice_list", select_only=True,
              help="The choice list this question draws its options from."),
    FieldSpec("label", kind="long", help="The question as respondents see it."),
    FieldSpec("hint", kind="long", help="Guidance shown under the question."),
    FieldSpec("required", kind="bool"),
    FieldSpec("relevant", help="Skip/display logic, e.g. ${age} >= 18."),
    FieldSpec("constraint", help="Answer validation on '.', e.g. . >= 0 and . <= 120."),
    FieldSpec("constraint_message", kind="long",
              help="Message shown when the constraint fails."),
    FieldSpec("calculation", help="Expression for a 'calculate' field."),
    FieldSpec("choice_filter", help="Cascading-select filter expression."),
    FieldSpec("appearance", help="Appearance hint, e.g. minimal, likert."),
    FieldSpec("default", help="Pre-filled default answer."),
]


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


# ---------------------------------------------------------------------------
# Full per-question editor (every authored field)
# ---------------------------------------------------------------------------
@dataclass
class FieldEdit:
    """One editable field of one question in the full review editor."""

    field_name: str
    label: str
    value: str
    kind: str                       # "text" | "long" | "bool"
    help: str = ""
    #: Set only for the four decision fields; "" for plain content fields.
    confidence: str = ""
    reason: str = ""
    needs_attention: bool = False


@dataclass
class QuestionReview:
    """All editable fields of a single question, for the grouped editor."""

    name: str
    label: str
    section: str = ""
    fields: List[FieldEdit] = field(default_factory=list)

    @property
    def needs_attention(self) -> bool:
        return any(f.needs_attention for f in self.fields)


def build_full_review(questionnaire: Questionnaire) -> List[QuestionReview]:
    """Every editable survey-row field, grouped by question, so a reviewer can
    edit the whole AI draft - not just the four decision fields. Questions
    with a field that needs attention sort first."""
    reviews: List[QuestionReview] = []
    for q in questionnaire.questions:
        if q.is_structural or not q.name:
            continue
        latest: Dict[str, Decision] = {}
        for d in q.decisions:
            latest[d.field_name] = d
        fields: List[FieldEdit] = []
        for spec in EDITABLE_FIELD_SPECS:
            if spec.select_only and not q.references_choices:
                continue
            fe = FieldEdit(field_name=spec.field_name, label=spec.label,
                           value=_current_value(q, spec.field_name),
                           kind=spec.kind, help=spec.help)
            d = latest.get(spec.field_name)
            if d is not None:
                fe.confidence = d.confidence
                fe.reason = d.reason
                fe.needs_attention = not (d.value or "").strip()
            fields.append(fe)
        reviews.append(QuestionReview(name=q.name,
                                      label=q.label or q.raw_label,
                                      section=q.section, fields=fields))
    reviews.sort(key=lambda r: (not r.needs_attention, r.name))
    return reviews


def apply_review_edits(questionnaire: Questionnaire,
                       edits: Dict[Tuple[str, str], str]) -> List[str]:
    """Apply human-reviewed values back onto the form.

    *edits* maps ``(question_name, field_name) -> value`` - the value the
    reviewer left in place (an implicit approval) or changed (an edit).
    Either way the field is set explicitly and a fresh high-confidence
    Decision is recorded, so the audit trail shows a human signed off.
    """
    notes: List[str] = []
    # Apply content edits before renames: a rename changes the key a question
    # is found by, so any other edit for that question (still keyed by its old
    # name) must land first. Within each group insertion order is preserved.
    ordered = sorted(edits.items(), key=lambda kv: kv[0][1] == "name")
    for (qname, field_name), raw_value in ordered:
        q = next((x for x in questionnaire.questions if x.name == qname), None)
        if q is None:
            notes.append(f"[Review] '{qname}' no longer exists; the "
                        f"{FIELD_LABELS.get(field_name, field_name)} edit "
                        f"was skipped.")
            continue

        if field_name == "name":
            notes.append(_apply_rename(questionnaire, q, raw_value))
            continue

        # ``required`` is a yes/no flag; every other field is free text.
        value = raw_value if field_name == "required" else (raw_value or "").strip()
        current = _current_value(q, field_name)
        _apply_field(q, field_name, value)
        verb = "approved" if value == current else "edited"
        if field_name in _DECISION_FIELDS:
            q.add_decision(field_name, value, "high",
                           f"Reviewed and {verb} by a human.")
        else:
            q.add_assumption(f"{FIELD_LABELS.get(field_name, field_name)} "
                             f"reviewed and {verb} by a human.")
        notes.append(f"[Review] '{q.name}' "
                    f"{FIELD_LABELS.get(field_name, field_name)} "
                    f"{verb}{': ' + value if verb == 'edited' else ''}.")
    return notes


# ---------------------------------------------------------------------------
_NAME_BAD = re.compile(r"[^a-z0-9_]")


def _sanitize_name(text: str) -> str:
    """Coerce free text into a valid XLSForm identifier (best effort)."""
    s = _NAME_BAD.sub("_", str(text).strip().lower())
    s = re.sub(r"_+", "_", s).strip("_")
    if s and s[0].isdigit():
        s = "q_" + s
    return s[:_MAX_NAME_LENGTH]


def _apply_rename(qn: Questionnaire, q: Question, raw_value: str) -> str:
    """Rename *q* and rewrite every ``${old}`` reference across the form."""
    old = q.name
    new = _sanitize_name(raw_value)
    if not new:
        return f"[Review] '{old}' name left blank; kept as is."
    if new == old:
        q.add_assumption("Variable name reviewed and approved by a human.")
        return f"[Review] '{old}' name approved."
    existing = {o.name for o in qn.questions if o is not q}
    err = check_variable_name(new, existing, max_length=_MAX_NAME_LENGTH)
    if err:
        return (f"[Review] '{old}' not renamed to '{new}': {err}; "
                f"kept as '{old}'.")
    q.name = new
    ref = re.compile(r"\$\{" + re.escape(old) + r"\}")
    for other in qn.questions:
        for attr in ("relevant", "constraint", "calculation",
                     "choice_filter", "default"):
            current = getattr(other, attr)
            if current:
                setattr(other, attr, ref.sub("${" + new + "}", current))
    q.add_assumption(f"Variable renamed '{old}' -> '{new}' by a human; all "
                     f"references were updated.")
    return f"[Review] '{old}' renamed to '{new}'; all references updated."


def _current_value(q: Question, field_name: str) -> str:
    if field_name == "name":
        return q.name
    if field_name == "type":
        return q.xlsform_type
    if field_name == "choice_list":
        return q.choice_list_name
    if field_name == "required":
        return "yes" if q.required else "no"
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
    if field_name == "required":
        q.required = str(value).strip().lower() in ("yes", "true", "1", "required")
        return
    attr = _DIRECT_ATTR.get(field_name)
    if attr:
        setattr(q, attr, value)
