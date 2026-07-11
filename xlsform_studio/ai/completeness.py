"""AI missing-question detection (optional AI feature; Module A4).

Purpose
-------
Infer what the survey is trying to measure and flag questions it probably
needs but doesn't have - the classic example being an anthropometry survey
collecting weight and MUAC but not height/length, which silently makes
weight-for-height indicators impossible. Recognising that a *set* of
questions implies a missing member is domain reasoning no rule engine can
enumerate.

Design
------
One API call per form: the question inventory (names, labels, types) plus
the user's optional survey-context description. The model returns
"potentially missing items", each with the reason it matters.

Safety
------
Strictly advisory: suggestions surface as ``ai_review`` findings
("Potentially missing: ...") capped at ``warning``. The tool **never
auto-adds a question** - inventing form content is an authorship decision
that stays with the human, full stop.

Inputs / outputs
----------------
A compiled :class:`~xlsform_studio.models.Questionnaire` and the survey
context; returns a list of
:class:`~xlsform_studio.validation.report_generator.Finding`.

Example
-------
>>> AICompletenessReviewer(client=None)  # doctest: +SKIP
"""

from __future__ import annotations

import json
from typing import List

from ..models import Questionnaire
from ..validation.report_generator import Finding
from .client import AIError, DeepSeekClient
from .prompt_safety import INJECTION_GUARD, frame_untrusted

_SYSTEM_PROMPT = (
    "You are a senior survey designer reviewing a questionnaire for "
    "completeness. You are given its question inventory as json (name, "
    "label, type) and optionally what the survey is about. Infer the "
    "survey's purpose and identify questions it very likely NEEDS but does "
    "not have - for example anthropometry with weight and MUAC but no "
    "height/length (blocks weight-for-height), an outcome without the "
    "denominator needed to report it, or consent/identifier fields a "
    "survey of this kind normally requires. Only flag items whose absence "
    "clearly undermines the survey's evident purpose - not nice-to-haves; "
    "if nothing important is missing, return an empty list. Respond ONLY "
    "with a json object of the form {\"missing\": [{\"item\": \"...\", "
    "\"reason\": \"...\"}]}." + INJECTION_GUARD)


class AICompletenessReviewer:
    """Flag likely-missing questions via DeepSeek. Advisory-only."""

    def __init__(self, client: DeepSeekClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    def review(self, questionnaire: Questionnaire,
               survey_context: str = "") -> List[Finding]:
        rows = [{"name": q.name, "label": q.label or q.raw_label,
                 "type": q.xlsform_type}
                for q in questionnaire.questions if not q.is_structural]
        if not rows:
            return []

        user_prompt = frame_untrusted("Survey context", survey_context)
        user_prompt += ("Question inventory (json):\n"
                        + json.dumps(rows, ensure_ascii=False))
        try:
            response = self.client.complete_json(
                _SYSTEM_PROMPT, user_prompt,
                max_tokens=max(800, len(rows) * 20))
        except AIError as exc:
            return [Finding("info", "ai_review",
                            f"AI completeness review could not run: {exc}")]

        findings: List[Finding] = []
        items = response.get("missing", [])
        if not isinstance(items, list):
            return [Finding("info", "ai_review",
                            "AI completeness response was not in the "
                            "expected shape.")]
        for item in items:
            if not isinstance(item, dict):
                continue
            what = (item.get("item") or "").strip()
            reason = (item.get("reason") or "").strip()
            if not what:
                continue
            message = f"Potentially missing: {what}"
            if reason:
                message += f" — {reason}"
            message += (" (Advisory only — the tool never adds questions; "
                        "add it in your source document if it belongs.)")
            findings.append(Finding("warning", "ai_review", message))
        return findings
