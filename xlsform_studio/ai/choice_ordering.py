"""AI choice-list ordering suggestions (optional AI feature).

Purpose
-------
Suggest a more logical order for a choice list's options - most common
answers first, thematic grouping, natural scales in order - which reduces
enumerator scrolling and mis-taps. Whether "Farming" should sit next to
"Fishing" is a semantic judgement, not a sortable property.

Design
------
One API call per form: every candidate list (name plus its options) is sent
together. Lists that are too short to benefit (< 3 options) and the
canonical ``yes_no`` list are excluded. The model returns, per list, the
option *names* in the suggested new order.

Safety
------
Advisory-only: this feature NEVER changes the form by itself. Each accepted
reordering is applied by
:func:`~xlsform_studio.ai.suggestions.apply_suggestions`, which
re-validates it. A suggestion is only produced when the proposed order is an
exact permutation of the existing option names - nothing added, nothing
dropped, nothing renamed - and actually differs from the current order.

Inputs / outputs
----------------
A compiled :class:`~xlsform_studio.models.Questionnaire`; returns
``(notes, suggestions)``.

Example
-------
>>> AIChoiceOrderingSuggester(client=None).suggest(Questionnaire())  # doctest: +SKIP
([], [])
"""

from __future__ import annotations

import json
from typing import List, Tuple

from ..models import Questionnaire
from ..validation import ai_validators
from .client import AIError, DeepSeekClient
from .suggestions import AISuggestion

#: Lists never offered for reordering.
_SKIP_LISTS = {"yes_no"}
_MIN_OPTIONS = 3

_SYSTEM_PROMPT = (
    "You are a survey design expert. You are given the choice lists of a "
    "survey as json: each list's name and its options ({name, label} pairs, "
    "in current order). Where a clearly better ordering exists - a natural "
    "scale in sequence, thematically related options adjacent, most common "
    "answers first, with catch-alls like 'Other', 'None', 'Refused' or "
    "'Don't know' kept last - propose the new order as the list of option "
    "NAMES (the machine values, not labels). The new order must contain "
    "exactly the same names, just reordered. Leave lists whose order is "
    "already fine (or meaningful, like ordered scales) out of the response; "
    "if nothing needs reordering, return an empty list. Respond ONLY with a "
    "json object of the form {\"orders\": [{\"list_name\": \"...\", "
    "\"order\": [\"...\"], \"reason\": \"...\"}]}.")


class AIChoiceOrderingSuggester:
    """Suggest logical choice-list ordering via DeepSeek. Advisory-only."""

    def __init__(self, client: DeepSeekClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    def suggest(self, questionnaire: Questionnaire
                ) -> Tuple[List[str], List[AISuggestion]]:
        candidates = {
            name: cl for name, cl in questionnaire.choice_lists.items()
            if name not in _SKIP_LISTS and len(cl.choices) >= _MIN_OPTIONS}
        if not candidates:
            return [], []

        rows = [{"list_name": name,
                 "options": [{"name": c.name, "label": c.label}
                             for c in cl.choices]}
                for name, cl in candidates.items()]
        try:
            response = self.client.complete_json(
                _SYSTEM_PROMPT, "Choice lists (json):\n"
                + json.dumps(rows, ensure_ascii=False),
                max_tokens=max(1000, sum(len(cl.choices)
                                         for cl in candidates.values()) * 25))
        except AIError as exc:
            return [f"[AI choice ordering] Skipped: {exc}"], []

        return self._to_suggestions(candidates, response)

    # ------------------------------------------------------------------
    def _to_suggestions(self, candidates: dict, response: dict
                        ) -> Tuple[List[str], List[AISuggestion]]:
        notes: List[str] = []
        suggestions: List[AISuggestion] = []
        items = response.get("orders", [])
        if not isinstance(items, list):
            return (["[AI choice ordering] Response was not in the expected "
                     "shape; no suggestions produced."], [])

        for item in items:
            if not isinstance(item, dict):
                continue
            list_name = item.get("list_name", "")
            cl = candidates.get(list_name)
            if cl is None:
                notes.append(f"[AI choice ordering] Rejected suggestion for "
                            f"unknown or excluded list '{list_name}'.")
                continue
            order = [str(n) for n in item.get("order", [])]
            current = cl.choice_names()
            error = ai_validators.check_permutation(current, order)
            if error:
                notes.append(f"[AI choice ordering] Rejected suggestion for "
                            f"'{list_name}': {error}.")
                continue
            if order == current:
                continue
            labels = {c.name: c.label for c in cl.choices}
            suggestions.append(AISuggestion(
                kind="choice_order", target=list_name,
                original=" → ".join(labels[n] for n in current),
                suggested=" → ".join(labels[n] for n in order),
                reason=(item.get("reason") or "").strip(),
                payload={"order": order}))

        if suggestions:
            notes.append(f"[AI choice ordering] {len(suggestions)} "
                        f"reordering suggestion(s) - review and accept to "
                        f"apply.")
        return notes, suggestions
