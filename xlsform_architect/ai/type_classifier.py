"""AI type-classification fallback (optional AI feature).

Purpose
-------
When the deterministic classifier (:mod:`xlsform_architect.engine.
question_classifier`) finds no keyword match and defaults a question to
``text``, ask the model for a better type instead. Keyword rules will always
have blind spots on unanticipated phrasing; a language model classifies by
meaning rather than by matching a fixed list.

Design
------
One API call per form: every question that fell back to the deterministic
default is batched into a single request. The model must choose from the
exact set of valid XLSForm base types (the same list the deployment
validator accepts) - anything else is rejected.

Safety
------
A suggested type is only applied if it is in the recognised type set. select
types are never proposed by this pass (choice lists cannot be safely
invented from a bare label), keeping the change low-risk: numeric/date/media
type corrections only.

Inputs
------
A compiled :class:`~xlsform_architect.models.Questionnaire`.

Outputs
-------
The questionnaire, mutated in place for reclassified questions (with the
constraint engine re-applied so the new type gets its matching validation
range), plus the list of notes describing what changed.

Example
-------
>>> AITypeClassifier(client=None).classify(Questionnaire())  # doctest: +SKIP
[]
"""

from __future__ import annotations

from typing import List

from ..engine.constraint_engine import ConstraintEngine
from ..models import Questionnaire
from .client import AIError, DeepSeekClient

# Deliberately excludes select_one/select_multiple/rank (need a choice list,
# which cannot be safely invented) and structural/meta types.
_ALLOWED_TYPES = (
    "integer", "decimal", "text", "date", "time", "datetime",
    "geopoint", "image", "audio", "video", "barcode", "note",
)

_SYSTEM_PROMPT = (
    "You are an XLSForm design expert. You are given questionnaire items "
    "whose type could not be determined by keyword rules and were defaulted "
    "to 'text'. For each item, choose the single best XLSForm field type "
    "from this exact list: " + ", ".join(_ALLOWED_TYPES) + ". "
    "If 'text' genuinely is the best fit, say so explicitly - do not force a "
    "different type. Respond ONLY with a json object of the form "
    "{\"classifications\": [{\"name\": \"...\", \"type\": \"...\", "
    "\"confidence\": \"high|medium|low\"}]}.")


class AITypeClassifier:
    """Reclassify keyword-fallback questions via DeepSeek, with validation."""

    def __init__(self, client: DeepSeekClient) -> None:
        self.client = client
        self.constraints = ConstraintEngine()

    # ------------------------------------------------------------------
    def classify(self, questionnaire: Questionnaire) -> List[str]:
        candidates = self._fallback_questions(questionnaire)
        if not candidates:
            return []

        try:
            response = self._request(candidates)
        except AIError as exc:
            return [f"[AI classification] Skipped ({len(candidates)} "
                    f"question(s) remain 'text'): {exc}"]

        return self._apply(questionnaire, candidates, response)

    # ------------------------------------------------------------------
    def _fallback_questions(self, qn: Questionnaire) -> list:
        out = []
        for q in qn.questions:
            if q.is_structural or q.xlsform_type != "text":
                continue
            if any("defaulted to 'text'" in a for a in q.assumptions):
                out.append(q)
        return out

    def _request(self, candidates: list) -> dict:
        import json
        items = [{"name": q.name, "label": q.label or q.raw_label}
                for q in candidates]
        user_prompt = "Items (json):\n" + json.dumps(items, ensure_ascii=False)
        return self.client.complete_json(
            _SYSTEM_PROMPT, user_prompt,
            max_tokens=max(500, len(candidates) * 60))

    def _apply(self, qn: Questionnaire, candidates: list, response: dict) -> List[str]:
        notes: List[str] = []
        by_name = {q.name: q for q in candidates}
        classifications = response.get("classifications", [])
        if not isinstance(classifications, list):
            return ["[AI classification] Response was not in the expected "
                    "shape; no changes applied."]

        seen = set()
        for item in classifications:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "")
            new_type = (item.get("type") or "").strip()
            confidence = item.get("confidence", "unknown")
            q = by_name.get(name)
            if q is None:
                continue
            seen.add(name)

            if new_type not in _ALLOWED_TYPES:
                notes.append(f"[AI classification] Rejected type "
                            f"'{new_type}' for '{name}' (not a recognised "
                            f"type); left as text.")
                continue
            if new_type == "text":
                continue  # AI agreed with the deterministic default

            q.xlsform_type = new_type
            q.constraint = ""  # clear the (inapplicable) text-type state
            self.constraints.apply(q)
            q.add_assumption(
                f"AI reclassified from 'text' to '{new_type}' "
                f"(confidence: {confidence}). Please review.")
            notes.append(f"[AI classification] '{name}': text -> "
                        f"{new_type} (confidence: {confidence}).")

        missing = set(by_name) - seen
        if missing:
            notes.append(f"[AI classification] No suggestion returned for "
                        f"{len(missing)} question(s); left as text.")
        return notes
