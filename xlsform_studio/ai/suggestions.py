"""AI suggestion model + deterministic apply step (optional AI layer).

Purpose
-------
Four of the AI features (question grouping, question rewording, choice-list
ordering, variable-name suggestions) are **advisory by design**: unlike the
gap-filling features (skip-logic fallback, constraints, translation) they
touch values the deterministic pipeline already produced confidently, so
they must never change the form silently. Instead each produces an
:class:`AISuggestion` - a reviewable original-vs-suggested pair - and the
form only changes when a human explicitly accepts it (UI accept buttons, or
programmatically via :func:`apply_suggestions`).

The apply step is fully deterministic and re-validates every suggestion at
apply time (the form may have changed since the suggestion was made):
a stale or structurally invalid acceptance is rejected with a note, never
half-applied.

Inputs
------
A compiled :class:`~xlsform_studio.models.Questionnaire` and the accepted
:class:`AISuggestion` objects.

Outputs
-------
The questionnaire mutated in place for each successfully applied suggestion
(with an "AI-suggested... accepted" assumption logged on the affected
question), plus notes describing what was applied or rejected.

Example
-------
>>> from xlsform_studio.models import Questionnaire, Question
>>> qn = Questionnaire(questions=[Question(name="a", label="Old", xlsform_type="text")])
>>> sug = AISuggestion(kind="rewording", target="a", original="Old",
...                    suggested="New", payload={"label": "New"})
>>> notes = apply_suggestions(qn, [sug])
>>> qn.questions[0].label
'New'
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from ..logging_config import get_audit_logger
from ..models import Questionnaire
from ..validation import ai_validators

_audit = get_audit_logger()

#: Suggestion kinds that :func:`apply_suggestions` knows how to apply.
#: "split" suggestions (rewording proposals to break a double-barreled
#: question in two) are display-only: splitting changes the data model and
#: must be done in the source document by the author.
APPLIABLE_KINDS = ("grouping", "rewording", "choice_order", "hint")


@dataclass
class AISuggestion:
    """One reviewable original-vs-suggested pair produced by an AI feature."""

    kind: str                 # "grouping" | "rewording" | "split" | "choice_order" | "hint"
    #: Question name (or choice list name for "choice_order"; "" for the
    #: form-level "grouping" suggestion).
    target: str
    original: str             # human-readable current value
    suggested: str            # human-readable proposed value
    reason: str = ""
    confidence: str = ""      # optional model-reported confidence
    #: Structured data needed to apply the suggestion deterministically.
    payload: Dict = field(default_factory=dict)
    applied: bool = False

    @property
    def appliable(self) -> bool:
        return self.kind in APPLIABLE_KINDS


# ---------------------------------------------------------------------------
def apply_suggestions(questionnaire: Questionnaire,
                      accepted: List[AISuggestion]) -> List[str]:
    """Apply accepted suggestions, re-validating each one at apply time."""
    notes: List[str] = []
    for sug in accepted:
        handler = _HANDLERS.get(sug.kind)
        if handler is None:
            _audit.warning("kind=%s target=%s outcome=rejected reason=%s",
                          sug.kind, sug.target or "form", "not appliable")
            notes.append(f"[AI suggestions] '{sug.kind}' suggestions are "
                        f"advisory-only and cannot be auto-applied "
                        f"('{sug.target}').")
            continue
        error = handler(questionnaire, sug)
        if error:
            _audit.warning("kind=%s target=%s outcome=rejected reason=%s",
                          sug.kind, sug.target or "form", error)
            notes.append(f"[AI suggestions] Could not apply {sug.kind} "
                        f"suggestion for '{sug.target}': {error}")
        else:
            sug.applied = True
            _audit.info("kind=%s target=%s outcome=applied",
                       sug.kind, sug.target or "form")
            notes.append(f"[AI suggestions] Applied accepted {sug.kind} "
                        f"suggestion for '{sug.target or 'form'}'.")
    return notes


# ---------------------------------------------------------------------------
def _apply_rewording(qn: Questionnaire, sug: AISuggestion) -> str:
    q = _question(qn, sug.target)
    if q is None:
        return "question no longer exists"
    label = (sug.payload.get("label") or "").strip()
    if not label:
        return "empty label"
    error = ai_validators.check_placeholders_preserved(
        q.label or q.raw_label, label)
    if error:
        return error
    q.label = label
    hint = (sug.payload.get("hint") or "").strip()
    if hint and not q.hint:            # a hint the author wrote stays
        q.hint = hint
    q.add_assumption(f"AI-suggested rewording accepted "
                     f"({sug.reason or 'clarity'}); original wording: "
                     f"'{sug.original}'.")
    return ""


def _apply_choice_order(qn: Questionnaire, sug: AISuggestion) -> str:
    cl = qn.choice_lists.get(sug.target)
    if cl is None:
        return "choice list no longer exists"
    order = [str(n) for n in sug.payload.get("order", [])]
    error = ai_validators.check_permutation(cl.choice_names(), order)
    if error:
        return error
    by_name = {c.name: c for c in cl.choices}
    cl.choices = [by_name[n] for n in order]
    for q in qn.questions:
        if q.list_name == sug.target:
            q.add_assumption(f"AI-suggested choice-list reordering for "
                             f"'{sug.target}' accepted "
                             f"({sug.reason or 'logical order'}).")
    return ""


def _apply_hint(qn: Questionnaire, sug: AISuggestion) -> str:
    q = _question(qn, sug.target)
    if q is None:
        return "question no longer exists"
    if q.hint:
        return "the question now has an author-written hint, which wins"
    hint = (sug.payload.get("hint") or "").strip()
    if not hint:
        return "empty hint"
    q.hint = hint
    q.add_assumption(f"AI-suggested enumerator instruction accepted as the "
                     f"hint ({sug.reason or 'field guidance'}).")
    return ""


def _apply_grouping(qn: Questionnaire, sug: AISuggestion) -> str:
    if any(q.is_structural for q in qn.questions):
        return ("the form has explicit group markers, which are respected "
                "verbatim; section suggestions cannot override them")
    sections = sug.payload.get("sections", [])
    real = [q for q in qn.questions if not q.is_structural]
    by_name = {q.name: q for q in real}
    order = [q.name for q in real]

    flat: List[str] = []
    for sec in sections:
        for name in sec.get("questions", []):
            if name not in by_name:
                return f"question '{name}' no longer exists"
            flat.append(name)
    if sorted(flat) != sorted(order):
        return "sections no longer cover every question exactly once"
    # Sections become contiguous begin/end groups at export; applying is
    # only safe when the plan keeps questions in their original order
    # (reordering could move a question before the fields its skip logic
    # references).
    if flat != order:
        return ("the suggested sections would reorder questions; apply "
                "this one manually in the source document instead")

    for sec in sections:
        for name in sec.get("questions", []):
            by_name[name].section = str(sec.get("name", "")).strip()
    for q in real:
        if q.section:
            q.add_assumption("AI-suggested section grouping accepted "
                             f"(assigned to '{q.section}').")
    return ""


def _question(qn: Questionnaire, name: str):
    return next((q for q in qn.questions if q.name == name), None)


_HANDLERS = {
    "rewording": _apply_rewording,
    "choice_order": _apply_choice_order,
    "grouping": _apply_grouping,
    "hint": _apply_hint,
}
