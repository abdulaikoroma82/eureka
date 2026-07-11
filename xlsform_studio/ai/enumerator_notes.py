"""AI enumerator instruction suggestions (optional AI feature; Module A9).

Purpose
-------
Draft the field guidance a good survey trainer would write per question -
how to probe without leading, what respondents commonly misunderstand,
what to clarify - as XLSForm ``hint`` text shown on the enumerator's
device. Anticipating misunderstandings is survey-methodology judgement, so
it belongs in the AI layer; *where* the text lands (the ``hint`` column)
and *whether* it lands (human acceptance) stay deterministic.

Design
------
One API call per form: every hint-less question's name, label, type and
options is sent together (guidance should be consistent in tone across the
form). Questions that already carry an author-written ``hint`` are never
even offered to the model - the author's text is authoritative, same
co-share contract as translation.

Safety
------
Advisory-only: produces :class:`~xlsform_studio.ai.suggestions.
AISuggestion` objects (kind ``"hint"``) for the accept/reject panel;
:func:`~xlsform_studio.ai.suggestions.apply_suggestions` re-checks at
apply time that the question still has no author hint. Suggestions must be
non-empty and reasonably short (device hints are glanced at, not read).

Inputs / outputs
----------------
A compiled :class:`~xlsform_studio.models.Questionnaire`; returns
``(notes, suggestions)``.

Example
-------
>>> AIEnumeratorNoteSuggester(client=None).suggest(Questionnaire())  # doctest: +SKIP
([], [])
"""

from __future__ import annotations

import json
from typing import List, Tuple

from ..models import Questionnaire
from .client import AIError, DeepSeekClient
from .suggestions import AISuggestion

#: Device hints are glanced at mid-interview; longer text gets ignored.
_MAX_HINT_CHARS = 200

_SYSTEM_PROMPT = (
    "You are a senior survey trainer writing enumerator guidance. You are "
    "given questionnaire items as json (name, label, type, options). For "
    "questions where field staff genuinely benefit from guidance - a "
    "probing technique, a common respondent misunderstanding to clarify, a "
    "recording pitfall - write ONE short instruction (max ~25 words, "
    "imperative voice, e.g. 'Probe for all sources; do not read the list "
    "aloud.'). Skip questions that need no guidance; if none do, return an "
    "empty list. Never guidance that leads the respondent toward an "
    "answer. Respond ONLY with a json object of the form "
    "{\"suggestions\": [{\"question_name\": \"...\", \"hint\": \"...\", "
    "\"reason\": \"...\"}]}.")


class AIEnumeratorNoteSuggester:
    """Suggest per-question enumerator hints via DeepSeek. Advisory-only."""

    def __init__(self, client: DeepSeekClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    def suggest(self, questionnaire: Questionnaire
                ) -> Tuple[List[str], List[AISuggestion]]:
        rows = []
        for q in questionnaire.questions:
            if q.is_structural or q.is_calculate or q.hint or not q.name:
                continue        # author hints are authoritative: not offered
            options = []
            if q.references_choices:
                parts = (q.xlsform_type or "").split()
                cl = questionnaire.choice_lists.get(
                    parts[1] if len(parts) >= 2 else q.list_name)
                if cl:
                    options = [c.label for c in cl.choices]
            rows.append({"name": q.name, "label": q.label or q.raw_label,
                         "type": q.xlsform_type, "options": options})
        if not rows:
            return [], []

        try:
            response = self.client.complete_json(
                _SYSTEM_PROMPT, "Questions (json):\n"
                + json.dumps(rows, ensure_ascii=False),
                max_tokens=max(1000, len(rows) * 60))
        except AIError as exc:
            return [f"[AI enumerator notes] Skipped: {exc}"], []

        return self._to_suggestions(questionnaire, response)

    # ------------------------------------------------------------------
    def _to_suggestions(self, qn: Questionnaire, response: dict
                        ) -> Tuple[List[str], List[AISuggestion]]:
        notes: List[str] = []
        suggestions: List[AISuggestion] = []
        items = response.get("suggestions", [])
        if not isinstance(items, list):
            return (["[AI enumerator notes] Response was not in the "
                     "expected shape; no suggestions produced."], [])

        by_name = {q.name: q for q in qn.questions}
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("question_name", "")
            q = by_name.get(name)
            if q is None:
                notes.append(f"[AI enumerator notes] Rejected suggestion "
                            f"for unknown question '{name}'.")
                continue
            if q.hint:
                notes.append(f"[AI enumerator notes] Rejected suggestion "
                            f"for '{name}': it already has an author-written "
                            f"hint, which stays authoritative.")
                continue
            hint = (item.get("hint") or "").strip()
            if not hint:
                continue
            if len(hint) > _MAX_HINT_CHARS:
                notes.append(f"[AI enumerator notes] Rejected suggestion "
                            f"for '{name}': too long for a device hint "
                            f"({len(hint)} chars).")
                continue
            suggestions.append(AISuggestion(
                kind="hint", target=name,
                original="(no hint)", suggested=hint,
                reason=(item.get("reason") or "").strip(),
                payload={"hint": hint}))

        if suggestions:
            notes.append(f"[AI enumerator notes] {len(suggestions)} "
                        f"instruction suggestion(s) - review and accept to "
                        f"add them as device hints.")
        return notes, suggestions
