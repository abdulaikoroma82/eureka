"""Round-trip reconciliation: merge an edited XLSForm back into the model.

Purpose
-------
Close the loop from *generator* to *canonical editor*. A form leaves the tool
as an XLSForm; someone edits it in Excel or a platform's form builder; it
comes back in. :func:`reconcile` merges that edited form against the model
snapshot from the run that produced it (the provenance sidecar - see
:mod:`~xlsform_studio.app.provenance`) so the re-import keeps everything the
workbook itself cannot carry: per-field confidence and the assumptions log.

The merge rule mirrors the in-app review panel
(:func:`~xlsform_studio.app.review.apply_review_edits`) exactly, so an edit
made in Excel is treated identically to one made in the UI:

* **Unchanged field** - keeps its original :class:`~xlsform_studio.models.Decision`
  and confidence from the prior model.
* **Changed field** - stamped a fresh *high-confidence* "reviewed by a human
  (edited XLSForm)" decision. The human deliberately changed it; that is the
  strongest possible signal, and it is never re-drafted by AI.
* **New question** (absent from the prior model) - flagged *low-confidence*
  for review, so nothing silently arrives unaudited.
* **Removed question** (present before, gone now) - logged.

Matching is by variable ``name``. A rename therefore reads as a delete plus
an add; treating it as a genuine rename is a future refinement (the D3 diff
engine already has the heuristic).
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from ..models import Question, Questionnaire

#: Survey-row fields whose value is compared across the round-trip. Structural
#: bookkeeping (raw_label, section_type, ...) is not user-editable in an
#: XLSForm and is left untouched.
_TRACKED_FIELDS: Tuple[str, ...] = (
    "xlsform_type", "label", "hint", "required", "relevant", "constraint",
    "constraint_message", "calculation", "choice_filter", "appearance",
    "default", "list_name",
)

#: Attribute -> the Decision ``field_name`` the review UI uses, so a
#: round-trip edit lands on the same confidence-tracked row an in-app edit
#: would. Fields with no dedicated review row fall back to their attribute
#: name.
_DECISION_FIELD: Dict[str, str] = {
    "xlsform_type": "type",
    "list_name": "choice_list",
}

#: Human-readable field names for the assumption notes.
_FIELD_LABEL: Dict[str, str] = {
    "xlsform_type": "Type", "label": "Label", "hint": "Hint",
    "required": "Required", "relevant": "Relevance", "constraint": "Constraint",
    "constraint_message": "Constraint message", "calculation": "Calculation",
    "choice_filter": "Choice filter", "appearance": "Appearance",
    "default": "Default", "list_name": "Choice list",
}


def reconcile(edited: Questionnaire,
              prior: Questionnaire) -> Tuple[Questionnaire, List[str]]:
    """Merge *edited* against the *prior* model snapshot, in place.

    Returns the (mutated) edited questionnaire and a list of assumption-log
    notes describing every carry-over, edit, addition and removal.
    """
    notes: List[str] = []
    prior_by_name = {q.name: q for q in prior.questions
                     if q.name and not q.is_structural}
    seen: set = set()

    for q in edited.questions:
        # begin/end group & repeat markers carry no authored provenance;
        # they are layout, re-derived on export, not questions to reconcile.
        if q.is_structural:
            continue
        ident = q.name or q.label or "(unnamed)"
        pj = prior_by_name.get(q.name) if q.name else None

        if pj is None:
            notes.append(
                f"[{ident}] New question introduced in the re-imported "
                f"XLSForm; review its type and logic before deployment.")
            q.add_decision(
                _DECISION_FIELD.get("xlsform_type", "type"),
                q.xlsform_type or "", "low",
                f"[{ident}] Added directly in an edited XLSForm - the tool "
                f"has no prior record of it, so please confirm the type.")
            continue

        seen.add(q.name)
        # Carry the prior provenance forward first; edited fields then append
        # a newer, authoritative decision on top of it.
        q.assumptions = list(pj.assumptions)
        q.decisions = list(pj.decisions)

        changed = _apply_field_changes(q, pj, ident)
        notes.extend(changed)
        if not changed:
            notes.append(
                f"[{ident}] Unchanged in the re-imported XLSForm; original "
                f"confidence and assumptions carried forward.")

    for name, pj in prior_by_name.items():
        if name not in seen:
            label = pj.label or name
            notes.append(
                f"[{name}] Question '{label}' was present in the previous "
                f"version but removed in the re-imported XLSForm.")

    return edited, notes


def _apply_field_changes(q: Question, prior: Question,
                         ident: str) -> List[str]:
    """Record a human-reviewed decision for every field that changed."""
    notes: List[str] = []
    for attr in _TRACKED_FIELDS:
        old, new = getattr(prior, attr), getattr(q, attr)
        if str(old) != str(new):
            field_name = _DECISION_FIELD.get(attr, attr)
            label = _FIELD_LABEL.get(attr, attr)
            q.add_decision(
                field_name, _as_text(new), "high",
                f"[{ident}] {label} changed in the re-imported XLSForm "
                f"(was {_display(old)}, now {_display(new)}); recorded as "
                f"reviewed by a human.")
            notes.append(
                f"[{ident}] {label} edited in the re-imported XLSForm.")
    return notes


def _as_text(value) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _display(value) -> str:
    text = _as_text(value).strip()
    return f"'{text}'" if text else "empty"
