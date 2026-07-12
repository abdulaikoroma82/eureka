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
* **Renamed question** - a question whose ``name`` is new but whose label
  matches a question that has otherwise disappeared is recognised as a
  rename (the same heuristic the D3 diff engine uses). Its provenance
  transfers to the new name, and the rename itself is recorded as a
  high-confidence human decision.
* **Removed question** (present before, gone now) - logged.

Matching is by variable ``name`` first, then by label for renames. Unlike
the in-app rename (:func:`~xlsform_studio.app.review.apply_review_edits`),
round-trip does **not** rewrite ``${old}`` references: the edited workbook is
authoritative for every field, so if the human renamed a variable but left a
reference dangling, the validator flags it honestly rather than the tool
silently "fixing" what the file actually says.
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
    matched_prior: set = set()

    # begin/end group & repeat markers carry no authored provenance; they are
    # layout, re-derived on export, not questions to reconcile.
    edited_questions = [q for q in edited.questions if not q.is_structural]

    # Pass 1: consume every exact name-match, so a later rename-by-label can
    # never steal a prior question that a real name-match still needs.
    unmatched: List[Question] = []
    for q in edited_questions:
        pj = prior_by_name.get(q.name) if q.name else None
        if pj is not None:
            matched_prior.add(q.name)
            notes.extend(_carry_and_diff(q, pj, q.name or q.label))
        else:
            unmatched.append(q)

    # Pass 2: each leftover is either a rename (label matches a now-missing
    # prior question) or genuinely new.
    for q in unmatched:
        ident = q.name or q.label or "(unnamed)"
        old_name = _find_rename(q, prior_by_name, matched_prior)
        if old_name is not None:
            pj = prior_by_name[old_name]
            matched_prior.add(old_name)
            q.assumptions = list(pj.assumptions)
            q.decisions = list(pj.decisions)
            q.add_decision(
                "name", q.name, "high",
                f"[{q.name}] Renamed from '{old_name}' in the re-imported "
                f"XLSForm; recorded as reviewed by a human. Note: any "
                f"${{{old_name}}} references are taken from the workbook "
                f"as-is and validated, not auto-rewritten.")
            notes.append(
                f"[{q.name}] Renamed from '{old_name}' in the re-imported "
                f"XLSForm; confidence and assumptions carried over.")
            notes.extend(_apply_field_changes(q, pj, ident))
            continue

        notes.append(
            f"[{ident}] New question introduced in the re-imported "
            f"XLSForm; review its type and logic before deployment.")
        q.add_decision(
            _DECISION_FIELD.get("xlsform_type", "type"),
            q.xlsform_type or "", "low",
            f"[{ident}] Added directly in an edited XLSForm - the tool "
            f"has no prior record of it, so please confirm the type.")

    for name, pj in prior_by_name.items():
        if name not in matched_prior:
            label = pj.label or name
            notes.append(
                f"[{name}] Question '{label}' was present in the previous "
                f"version but removed in the re-imported XLSForm.")

    return edited, notes


def _carry_and_diff(q: Question, pj: Question, ident: str) -> List[str]:
    """Carry prior provenance onto a name-matched question, then record any
    field-level edits."""
    # Carry the prior provenance forward first; edited fields then append a
    # newer, authoritative decision on top of it.
    q.assumptions = list(pj.assumptions)
    q.decisions = list(pj.decisions)
    changed = _apply_field_changes(q, pj, ident)
    if changed:
        return changed
    return [f"[{ident}] Unchanged in the re-imported XLSForm; original "
            f"confidence and assumptions carried forward."]


def _find_rename(q: Question, prior_by_name: Dict[str, Question],
                 matched_prior: set) -> "str | None":
    """The old name of an unconsumed prior question sharing this label, or
    None. Labels must be non-empty to match, so two blank-label questions
    never collapse into a spurious rename."""
    label = (q.label or q.raw_label or "").strip()
    if not label:
        return None
    for name, pj in prior_by_name.items():
        if name in matched_prior:
            continue
        if (pj.label or pj.raw_label or "").strip() == label:
            return name
    return None


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
