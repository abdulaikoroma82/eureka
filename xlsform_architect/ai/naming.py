"""AI variable-name suggestions (optional AI feature).

Purpose
-------
Offer a more natural variable name where the deterministic naming engine's
stopword-stripping produced something awkward (e.g. ``many_years_lived_here``
for "How many years have you lived here?" - ``years_lived_here`` reads
better in an analysis script).

The deterministic name is - and stays - the applied one. The README's
design note holds: naming must be free, instant and **stable** (the same
question always yields the same name across re-runs, or version history and
diffs break). This feature therefore only ever *stores a suggestion* for a
human to accept; nothing is renamed automatically.

Design
------
One API call per form: every question's name and label is sent together
(name consistency across the form is part of what's being judged).

Safety
------
Advisory-only, applied exclusively through
:func:`~xlsform_architect.ai.suggestions.apply_suggestions`, which
re-validates and - crucially - rewrites every ``${old_name}`` reference in
the whole form when a rename is accepted, so no expression is left pointing
at a name that no longer exists. A suggestion is only produced when the
proposed name passes the platform rules (starts with a letter, identifier
characters only, within the length limit) and collides with no existing
name or other suggestion.

Inputs / outputs
----------------
A compiled :class:`~xlsform_architect.models.Questionnaire`; returns
``(notes, suggestions)``.

Example
-------
>>> AINamingSuggester(client=None).suggest(Questionnaire())  # doctest: +SKIP
([], [])
"""

from __future__ import annotations

import json
from typing import List, Tuple

from ..models import Questionnaire
from ..validation import ai_validators
from .client import AIError, DeepSeekClient
from .suggestions import AISuggestion

_SYSTEM_PROMPT = (
    "You are a data management expert reviewing XLSForm variable names. You "
    "are given questions as json (name, label). Where a name is awkward, "
    "misleading, or would confuse an analyst reading the exported dataset, "
    "suggest a better snake_case name: short, starts with a letter, only "
    "lowercase letters, digits and underscores, at most 40 characters, and "
    "consistent in style with the form's other names. Leave good names "
    "alone - only flag genuinely awkward ones; if all names are fine, "
    "return an empty list. Respond ONLY with a json object of the form "
    "{\"suggestions\": [{\"question_name\": \"...\", \"suggested_name\": "
    "\"...\", \"reason\": \"...\"}]}.")


class AINamingSuggester:
    """Suggest clearer variable names via DeepSeek. Advisory-only."""

    def __init__(self, client: DeepSeekClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    def suggest(self, questionnaire: Questionnaire
                ) -> Tuple[List[str], List[AISuggestion]]:
        rows = [{"name": q.name, "label": q.label or q.raw_label}
                for q in questionnaire.questions
                if not q.is_structural and q.name]
        if not rows:
            return [], []

        try:
            response = self.client.complete_json(
                _SYSTEM_PROMPT, "Questions (json):\n"
                + json.dumps(rows, ensure_ascii=False),
                max_tokens=max(1000, len(rows) * 40))
        except AIError as exc:
            return [f"[AI naming] Skipped: {exc}"], []

        return self._to_suggestions(questionnaire, response)

    # ------------------------------------------------------------------
    def _to_suggestions(self, qn: Questionnaire, response: dict
                        ) -> Tuple[List[str], List[AISuggestion]]:
        notes: List[str] = []
        suggestions: List[AISuggestion] = []
        items = response.get("suggestions", [])
        if not isinstance(items, list):
            return (["[AI naming] Response was not in the expected shape; "
                     "no suggestions produced."], [])

        by_name = {q.name: q for q in qn.questions}
        taken = {q.name for q in qn.questions if q.name}
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("question_name", "")
            q = by_name.get(name)
            if q is None:
                notes.append(f"[AI naming] Rejected suggestion for unknown "
                            f"question '{name}'.")
                continue
            new = (item.get("suggested_name") or "").strip()
            if not new or new == name:
                continue
            error = ai_validators.check_variable_name(new, taken)
            if error:
                notes.append(f"[AI naming] Rejected suggested name '{new}' "
                            f"for '{name}': {error}.")
                continue
            taken.add(new)          # later suggestions must not collide either
            suggestions.append(AISuggestion(
                kind="naming", target=name, original=name, suggested=new,
                reason=(item.get("reason") or "").strip(),
                payload={"name": new}))

        if suggestions:
            notes.append(f"[AI naming] {len(suggestions)} name "
                        f"suggestion(s) - the deterministic names stay in "
                        f"use unless you accept a change.")
        return notes, suggestions
