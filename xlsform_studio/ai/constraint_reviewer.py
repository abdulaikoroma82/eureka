"""AI cross-field constraint suggestions (optional AI feature).

Purpose
-------
Suggest validation constraints that depend on the *relationship* between two
or more questions - e.g. "end date must be on or after start date",
"confirmation email must match email". The deterministic constraint engine
(:mod:`xlsform_studio.engine.constraint_engine`) can only ever look at one
question's own label and type, so it structurally cannot express these; a
model reading the whole form's labels can recognise the relationship.

Design
------
One API call per form: every question's name, label and type is sent
together, since spotting a relationship (e.g. a "start date" and an "end
date" question) is inherently a cross-question task.

Safety
------
A suggestion is only applied when every ``${...}`` reference inside the
proposed expression names a real, *different* question (a constraint
referencing only itself is rejected - that is the deterministic engine's
job, not this one's). If the target question already has a constraint (very
common: the deterministic engine adds a generic one, e.g. a date "not in the
future" rule), the new condition is **combined with "and"** rather than
discarded or blocking the suggestion - the single-field rule the
deterministic engine is good at and the cross-field rule only AI can add
both end up enforced. A suggestion is only dropped outright when it would
duplicate a reference already present in the existing constraint (an
ambiguous case left for manual review rather than guessed at). Rejected
suggestions are reported, never silently applied.

Inputs
------
A compiled :class:`~xlsform_studio.models.Questionnaire`.

Outputs
-------
The questionnaire, mutated in place for questions that received a validated
cross-field constraint, plus the list of notes describing what changed.

Example
-------
>>> AICrossFieldConstraintReviewer(client=None).suggest(Questionnaire())  # doctest: +SKIP
[]
"""

from __future__ import annotations

import json
import re
from typing import List

from ..models import Questionnaire
from .client import AIError, DeepSeekClient

_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

_SYSTEM_PROMPT = (
    "You are an XLSForm validation expert. You are given a compiled survey "
    "(name, label, type, and any existing constraint for each question). "
    "Find pairs or groups of questions whose values constrain each other - "
    "for example an end date that must be on or after a start date, a "
    "confirmation field that must match another, or a value that must be "
    "less than a related maximum - and propose an XLSForm 'constraint' "
    "expression for the LATER (dependent) question, referencing the other "
    "field(s) as ${field_name}. Only propose a constraint for a question "
    "that does not already have one. Do not propose single-field range "
    "constraints (e.g. age between 0 and 120) - assume those are already "
    "handled elsewhere; only propose constraints that reference ANOTHER "
    "field. Only propose a change when confident; omit anything ambiguous. "
    "Respond ONLY with a json object of the form "
    "{\"suggestions\": [{\"question_name\": \"...\", \"constraint\": \"...\", "
    "\"constraint_message\": \"...\", \"rationale\": \"...\"}]}.")


class AICrossFieldConstraintReviewer:
    """Suggest cross-field validation constraints via DeepSeek."""

    def __init__(self, client: DeepSeekClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    def suggest(self, questionnaire: Questionnaire) -> List[str]:
        rows = self._survey_summary(questionnaire)
        if not rows:
            return []

        valid_names = {q.name for q in questionnaire.questions if q.name}
        try:
            response = self.client.complete_json(
                _SYSTEM_PROMPT, "Survey (json):\n" + json.dumps(rows, ensure_ascii=False),
                max_tokens=max(1000, len(rows) * 50))
        except AIError as exc:
            return [f"[AI cross-field constraints] Skipped: {exc}"]

        return self._apply(questionnaire, response, valid_names)

    # ------------------------------------------------------------------
    def _survey_summary(self, qn: Questionnaire) -> list:
        return [{"name": q.name, "label": q.label or q.raw_label,
                 "type": q.xlsform_type, "constraint": q.constraint}
                for q in qn.questions if not q.is_structural]

    def _apply(self, qn: Questionnaire, response: dict, valid_names: set) -> List[str]:
        notes: List[str] = []
        by_name = {q.name: q for q in qn.questions}
        suggestions = response.get("suggestions", [])
        if not isinstance(suggestions, list):
            return ["[AI cross-field constraints] Response was not in the "
                    "expected shape; no changes applied."]

        for sug in suggestions:
            if not isinstance(sug, dict):
                continue
            name = sug.get("question_name", "")
            expr = (sug.get("constraint") or "").strip()
            message = (sug.get("constraint_message") or "").strip()
            rationale = sug.get("rationale", "")

            target = by_name.get(name)
            if target is None:
                notes.append(f"[AI cross-field constraints] Rejected "
                            f"suggestion for unknown question '{name}'.")
                continue
            if not expr:
                continue

            refs = set(_REF.findall(expr))
            unknown = refs - valid_names
            if unknown:
                notes.append(f"[AI cross-field constraints] Rejected "
                            f"suggestion for '{name}': references unknown "
                            f"field(s) {sorted(unknown)}.")
                continue
            if not refs:
                notes.append(f"[AI cross-field constraints] Rejected "
                            f"suggestion for '{name}': does not reference "
                            f"another field (not a cross-field constraint).")
                continue
            if name in refs:
                notes.append(f"[AI cross-field constraints] Rejected "
                            f"suggestion for '{name}': references itself.")
                continue

            existing_refs = set(_REF.findall(target.constraint))
            if target.constraint and (refs & existing_refs):
                notes.append(f"[AI cross-field constraints] '{name}' already "
                            f"references {sorted(refs & existing_refs)} in "
                            f"its constraint; AI suggestion not applied to "
                            f"avoid a conflict (review manually: `{expr}`).")
                continue

            if target.constraint:
                # Combine: keep the deterministic engine's (usually
                # single-field) rule intact and add the cross-field one.
                # Record both parts in the assumption so the verification
                # checklist can quote exactly what was original vs added.
                original = target.constraint
                target.constraint = f"({target.constraint}) and ({expr})"
                target.constraint_message = (
                    f"{target.constraint_message} {message}".strip()
                    if message else target.constraint_message)
                verb = "Combined"
                target.add_assumption(
                    f"AI-suggested cross-field constraint "
                    f"({rationale or 'no rationale given'}). "
                    f"Original: `{original}`. AI addition: `{expr}`. "
                    f"Please review before deployment.")
            else:
                target.constraint = expr
                target.constraint_message = message or target.constraint_message
                verb = "Applied"
                target.add_assumption(
                    f"AI-suggested cross-field constraint "
                    f"({rationale or 'no rationale given'}). "
                    f"AI addition: `{expr}`. "
                    f"Please review before deployment.")
            notes.append(f"[AI cross-field constraints] {verb} suggested "
                        f"constraint on '{name}': `{expr}` - please review.")
        return notes
