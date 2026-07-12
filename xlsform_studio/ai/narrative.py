"""AI quality narrative (optional AI feature; Hybrid H1 / Module A15).

Purpose
-------
Turn the deterministic quality numbers into an executive summary a
non-technical stakeholder can read - e.g. *"This questionnaire shows
strong structural quality but moderate respondent burden, driven by the
household roster section."* The division of authority is strict: **rules
compute every number** (the Form Quality Index, the duration estimate,
the validation findings); AI only narrates them. Turn AI off and the
numbers are identical - just not narrated.

Design
------
One API call per form. The prompt carries only the already-computed
metrics (scores, minutes, risk rating, finding counts, observations) plus
the form's title and size - never raw respondent-facing content beyond
question counts, so the narrative stays grounded in the audited numbers
rather than the model's own re-review.

Safety
------
Advisory-only: the narrative is a string attached to the QA report,
clearly labelled as AI-written. It cannot change a score, a finding, or
the deployment verdict. Fails open like every AI feature.

Inputs
------
The :class:`~xlsform_studio.analysis.quality_score.QualityIndex`, the
:class:`~xlsform_studio.analysis.duration.DurationEstimate`, the
:class:`~xlsform_studio.validation.report_generator.ValidationReport`,
and basic form metadata.

Outputs
-------
``(narrative, notes)`` - the narrative is "" when the feature is off or
the call fails.

Example
-------
>>> AIQualityNarrator(client=None)  # doctest: +SKIP
"""

from __future__ import annotations

import json
from typing import List, Tuple

from ..analysis.duration import DurationEstimate
from ..analysis.quality_score import QualityIndex
from ..models import Questionnaire
from ..validation.report_generator import ValidationReport
from .client import AIError, DeepSeekClient

_SYSTEM_PROMPT = (
    "You are a survey quality assurance lead writing the executive summary "
    "of a QA report. You are given ONLY pre-computed, audited metrics for a "
    "questionnaire (quality scores per category, an interview-duration "
    "estimate, validation finding counts, deployment-readiness findings, "
    "and the rule engine's own observations). Write 2-5 sentences of "
    "plain, professional prose summarising the form's overall quality and "
    "readiness to deploy: lead with the strongest aspects, name the "
    "biggest risks, comment on operational readiness (translations, "
    "media, device fit, interview length and what they mean for training "
    "and logistics) when the readiness findings warrant it, and end with "
    "the single most valuable improvement. Base every claim strictly on "
    "the metrics provided - do not invent problems or praise not "
    "supported by them, and do not restate raw numbers the report already "
    "shows unless they carry the point. Respond ONLY with a json object "
    "of the form {\"narrative\": \"...\"}.")


class AIQualityNarrator:
    """Narrate the deterministic quality metrics via DeepSeek."""

    def __init__(self, client: DeepSeekClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    def narrate(self, questionnaire: Questionnaire,
                quality: QualityIndex, duration: DurationEstimate,
                report: ValidationReport) -> Tuple[str, List[str]]:
        payload = {
            "form_title": questionnaire.settings.form_title,
            "question_count": duration.question_count,
            "quality_index": quality.to_dict(),
            "duration_estimate": duration.to_dict(),
            "validation": {
                "errors": len(report.errors),
                "warnings": len(report.warnings),
                "is_valid": report.is_valid,
            },
            # H5: rules assess technical readiness; the narrative adds the
            # operational reading of those same findings.
            "readiness_findings": [
                f.message for f in report.findings
                if f.category == "readiness"],
        }
        try:
            response = self.client.complete_json(
                _SYSTEM_PROMPT,
                "Metrics (json):\n" + json.dumps(payload, ensure_ascii=False),
                max_tokens=400)
        except AIError as exc:
            return "", [f"[AI narrative] Skipped: {exc}"]

        narrative = str(response.get("narrative", "")).strip()
        if not narrative:
            return "", ["[AI narrative] The model returned no narrative."]
        return narrative, ["[AI narrative] Added an executive summary to "
                           "the QA report (AI-written, advisory only)."]
