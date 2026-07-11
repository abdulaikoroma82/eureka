"""AI question rewording suggestions (optional AI feature).

Purpose
-------
Detect questions whose wording will cause trouble in the field - ambiguous,
double-barreled ("Do you own a phone and a radio?"), leading ("You wash
your hands, right?"), or jargon-heavy - and suggest a clearer version.
Whether a sentence is leading or ambiguous is a language judgement outside
any rule engine's reach.

Design
------
One API call per form: every question's name and label (plus hint) is sent
together, since consistency of register across questions is part of what's
being reviewed. The model returns a suggested label (and optional hint) with
a reason, or - for a double-barreled question - a proposal to split it in
two.

Safety
------
Advisory-only: this feature NEVER changes the form by itself. Each accepted
label suggestion is applied by
:func:`~xlsform_studio.ai.suggestions.apply_suggestions`, which
re-validates it. A suggestion is only produced when it is non-empty,
actually differs from the original, and preserves every ``${...}``
placeholder the original label contains. Split proposals are display-only
(kind ``"split"``): splitting one question into two changes the data model,
so it must be done in the source document by the author - the tool never
invents new questions.

Inputs / outputs
----------------
A compiled :class:`~xlsform_studio.models.Questionnaire`; returns
``(notes, suggestions)``.

Example
-------
>>> AIRewordingSuggester(client=None).suggest(Questionnaire())  # doctest: +SKIP
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
    "You are a survey methodology expert. You are given questionnaire items "
    "as json (name, label, hint). Identify labels that are ambiguous, "
    "double-barreled (asking two things at once), leading, or jargon-heavy "
    "for a general respondent, and suggest a clearer wording that preserves "
    "the exact meaning and any ${...} placeholders verbatim. Optionally "
    "suggest a short hint. For a double-barreled question, instead propose "
    "splitting it: provide 'split_into' as a list of two or more separate "
    "question labels. Leave well-worded questions alone - only flag genuine "
    "problems; if everything reads fine, return an empty list. Respond ONLY "
    "with a json object of the form {\"suggestions\": [{\"question_name\": "
    "\"...\", \"label\": \"...\", \"hint\": \"...\", \"reason\": \"...\", "
    "\"split_into\": [\"...\"]}]} where 'label' and 'split_into' are "
    "mutually exclusive.")


class AIRewordingSuggester:
    """Suggest clearer question wording via DeepSeek. Advisory-only."""

    def __init__(self, client: DeepSeekClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    def suggest(self, questionnaire: Questionnaire
                ) -> Tuple[List[str], List[AISuggestion]]:
        rows = [{"name": q.name, "label": q.label or q.raw_label,
                 "hint": q.hint}
                for q in questionnaire.questions
                if not q.is_structural and (q.label or q.raw_label)]
        if not rows:
            return [], []

        try:
            response = self.client.complete_json(
                _SYSTEM_PROMPT, "Questions (json):\n"
                + json.dumps(rows, ensure_ascii=False),
                max_tokens=max(1500, len(rows) * 80))
        except AIError as exc:
            return [f"[AI rewording] Skipped: {exc}"], []

        return self._to_suggestions(questionnaire, response)

    # ------------------------------------------------------------------
    def _to_suggestions(self, qn: Questionnaire, response: dict
                        ) -> Tuple[List[str], List[AISuggestion]]:
        notes: List[str] = []
        suggestions: List[AISuggestion] = []
        items = response.get("suggestions", [])
        if not isinstance(items, list):
            return (["[AI rewording] Response was not in the expected shape; "
                     "no suggestions produced."], [])

        by_name = {q.name: q for q in qn.questions}
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("question_name", "")
            q = by_name.get(name)
            if q is None:
                notes.append(f"[AI rewording] Rejected suggestion for "
                            f"unknown question '{name}'.")
                continue
            original = q.label or q.raw_label
            reason = (item.get("reason") or "").strip()

            split = item.get("split_into")
            if isinstance(split, list) and len(split) >= 2:
                parts = [str(p).strip() for p in split]
                if not all(parts):
                    notes.append(f"[AI rewording] Rejected split proposal "
                                f"for '{name}': contains an empty label.")
                    continue
                suggestions.append(AISuggestion(
                    kind="split", target=name, original=original,
                    suggested=" | ".join(parts), reason=reason,
                    payload={"split_into": parts}))
                notes.append(f"[AI rewording] '{name}' looks double-barreled; "
                            f"suggested splitting it into {len(parts)} "
                            f"questions (edit the source document to apply).")
                continue

            label = (item.get("label") or "").strip()
            if not label or label == original:
                continue
            error = ai_validators.check_placeholders_preserved(original, label)
            if error:
                notes.append(f"[AI rewording] Rejected suggestion for "
                            f"'{name}': {error}.")
                continue
            suggestions.append(AISuggestion(
                kind="rewording", target=name, original=original,
                suggested=label, reason=reason,
                payload={"label": label,
                         "hint": (item.get("hint") or "").strip()}))

        if suggestions:
            notes.append(f"[AI rewording] {len(suggestions)} wording "
                        f"suggestion(s) - review and accept to apply.")
        return notes, suggestions
