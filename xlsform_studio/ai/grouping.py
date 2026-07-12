"""AI question grouping suggestions (optional AI feature).

Purpose
-------
Suggest a logical section structure for a form whose source document didn't
provide one (or provided a poor one). Grouping questions by theme improves
enumerator flow and makes long forms navigable, but deciding that "water
source", "latrine type" and "handwashing station" belong together is a
semantic judgement no keyword rule can make reliably.

Design
------
One API call per form: every question's index, name, label and current
section is sent together (grouping is inherently a whole-form task).
The model returns a list of sections, each naming the question indices it
should contain.

Safety
------
Advisory-only: this feature NEVER changes the form by itself. It produces
one :class:`~xlsform_studio.ai.suggestions.AISuggestion` for the user to
accept or reject; acceptance is applied (and re-validated) by
:func:`~xlsform_studio.ai.suggestions.apply_suggestions`. The suggestion
is only produced at all when the deterministic checks pass: every question
covered exactly once, section names unique and non-empty. Forms that already
carry explicit begin/end group markers are skipped entirely - authored
structure is respected verbatim.

Inputs / outputs
----------------
A compiled :class:`~xlsform_studio.models.Questionnaire`; returns
``(notes, suggestions)``.

Example
-------
>>> AIGroupingSuggester(client=None).suggest(Questionnaire())  # doctest: +SKIP
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
    "You are a survey design expert. You are given an ordered list of "
    "questionnaire items as json, each with an index, name, label and its "
    "current section (may be empty). Group the questions into logical, "
    "thematically coherent sections, KEEPING THE ORIGINAL QUESTION ORDER - "
    "sections must be contiguous runs of the given indices. Use short, "
    "clear section titles (e.g. 'Demographics', 'Water and Sanitation'). "
    "Every question index must appear in exactly one section, and section "
    "names must be unique. If the current sectioning is already good, "
    "return an empty list. Respond ONLY with a json object of the form "
    "{\"sections\": [{\"name\": \"...\", \"question_indices\": [0, 1]}]}.")


class AIGroupingSuggester:
    """Suggest a section structure via DeepSeek. Advisory-only."""

    def __init__(self, client: DeepSeekClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    def suggest(self, questionnaire: Questionnaire
                ) -> Tuple[List[str], List[AISuggestion]]:
        if any(q.is_structural for q in questionnaire.questions):
            return (["[AI grouping] Skipped: the form defines explicit "
                     "groups, which are respected verbatim."], [])
        real = [q for q in questionnaire.questions if not q.is_structural]
        if len(real) < 2:
            return [], []

        rows = [{"index": i, "name": q.name, "label": q.label or q.raw_label,
                 "section": q.section} for i, q in enumerate(real)]
        try:
            response = self.client.complete_json(
                _SYSTEM_PROMPT, "Questions (json):\n"
                + json.dumps(rows, ensure_ascii=False),
                max_tokens=max(1000, len(rows) * 30))
        except AIError as exc:
            return [f"[AI grouping] Skipped: {exc}"], []

        return self._to_suggestion(real, response)

    # ------------------------------------------------------------------
    def _to_suggestion(self, real, response: dict
                       ) -> Tuple[List[str], List[AISuggestion]]:
        sections = response.get("sections", [])
        if not isinstance(sections, list):
            return (["[AI grouping] Response was not in the expected shape; "
                     "no suggestion produced."], [])
        if not sections:
            return (["[AI grouping] The current section structure was judged "
                     "fine; no changes suggested."], [])
        if not all(isinstance(s, dict) for s in sections):
            return (["[AI grouping] Response was not in the expected shape; "
                     "no suggestion produced."], [])

        index_groups = [s.get("question_indices", []) for s in sections]
        error = (ai_validators.check_covers_exactly_once(index_groups, len(real))
                 or ai_validators.check_unique_nonempty(
                     s.get("name", "") for s in sections))
        if error:
            return ([f"[AI grouping] Rejected the model's section plan: "
                     f"{error}."], [])

        payload_sections = [
            {"name": str(s.get("name", "")).strip(),
             "questions": [real[i].name for i in s.get("question_indices", [])]}
            for s in sections]
        suggestion = AISuggestion(
            kind="grouping", target="",
            original=self._describe_current(real),
            suggested="\n".join(
                f"{s['name']}: {', '.join(s['questions'])}"
                for s in payload_sections),
            reason="Thematic sections improve enumerator flow on long forms.",
            payload={"sections": payload_sections})
        return ([f"[AI grouping] Suggested {len(sections)} section(s) - "
                 f"review and accept to apply."], [suggestion])

    @staticmethod
    def _describe_current(real) -> str:
        lines, current = [], object()
        for q in real:
            if q.section != current:
                current = q.section
                lines.append(f"{q.section or '(no section)'}: {q.name}")
            else:
                lines[-1] += f", {q.name}"
        return "\n".join(lines)
