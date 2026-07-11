"""AI plain-English finding explanations (optional AI feature).

Purpose
-------
Add a short, human-readable explanation to the deterministic validator's
findings, for a non-technical reader who sees "Select question 's' uses
undefined list 'nolist'" and doesn't immediately know what that means or how
to fix it.

This is a genuine co-share between rules and AI on the *same* output, but a
strictly divided one: **rules own every fact** - level, category, the
message itself, and whether the form is valid at all. AI only ever adds an
``explanation`` string alongside a finding; it never changes, removes, adds,
or reinterprets a finding, and it runs strictly after validation has already
produced its authoritative result. A finding's severity and meaning are
exactly as true with AI off as with it on - AI only makes it easier to read.

Design
------
One API call per form: every error/warning finding (skipping ``info`` -
usually self-explanatory - and the ``ai_review`` category, whose findings
already carry AI's own explanation in the message) is batched together,
tagged by index so the response can be matched back positionally.

Inputs
------
A :class:`~xlsform_studio.validation.report_generator.ValidationReport`
already produced by :class:`~xlsform_studio.validation.validator.Validator`.

Outputs
-------
The report's findings, mutated in place: ``explanation`` is set on the
matched findings. Returns the list of notes.

Example
-------
>>> from xlsform_studio.validation.report_generator import ValidationReport
>>> AIFindingExplainer(client=None).explain(ValidationReport())  # doctest: +SKIP
[]
"""

from __future__ import annotations

import json
from typing import List

from ..validation.report_generator import Finding, ValidationReport
from .client import AIError, DeepSeekClient

_SYSTEM_PROMPT = (
    "You are helping a non-technical survey designer understand XLSForm "
    "validation results. You are given a json list of findings (each with "
    "an index, category, level and message). For each one, write ONE short "
    "sentence in plain English explaining what it means and, if relevant, "
    "the general kind of fix (do not invent a specific field name or value "
    "that was not already in the message). Keep jargon to a minimum. "
    "Respond ONLY with a json object of the form "
    "{\"explanations\": [{\"index\": 0, \"explanation\": \"...\"}]}.")

#: Findings in these categories already carry their own explanation in the
#: message (ai_review) or are rarely worth elaborating (info-level notes).
_SKIP_CATEGORIES = {"ai_review"}


class AIFindingExplainer:
    """Add plain-English explanations to existing findings via DeepSeek."""

    def __init__(self, client: DeepSeekClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    def explain(self, report: ValidationReport) -> List[str]:
        candidates = [
            (i, f) for i, f in enumerate(report.findings)
            if f.level in ("error", "warning")
            and f.category not in _SKIP_CATEGORIES
            and not f.explanation
        ]
        if not candidates:
            return []

        rows = [{"index": i, "category": f.category, "level": f.level,
                "message": f.message} for i, f in candidates]

        try:
            response = self.client.complete_json(
                _SYSTEM_PROMPT, "Findings (json):\n" + json.dumps(rows, ensure_ascii=False),
                max_tokens=max(800, len(rows) * 60))
        except AIError as exc:
            return [f"[AI explanations] Skipped ({len(candidates)} "
                    f"finding(s) left unexplained): {exc}"]

        return self._apply(report, dict(candidates), response)

    # ------------------------------------------------------------------
    def _apply(self, report: ValidationReport, by_index: dict,
              response: dict) -> List[str]:
        explanations = response.get("explanations", [])
        if not isinstance(explanations, list):
            return ["[AI explanations] Response was not in the expected "
                    "shape; no explanations added."]

        applied = 0
        for item in explanations:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            text = (item.get("explanation") or "").strip()
            finding = by_index.get(idx)
            if finding is None or not text:
                continue
            finding.explanation = text
            applied += 1

        return [f"[AI explanations] Added plain-English explanations to "
                f"{applied}/{len(by_index)} finding(s)."]
