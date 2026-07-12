"""AI objective-coverage review (optional AI feature; Modules A5 + H2).

Purpose
-------
Answer the question every M&E reviewer asks before sign-off: *does this
questionnaire actually measure what the study set out to measure?* The
user supplies their objectives / indicators / research questions (one per
line); the tool maps each to the questions that inform it and flags the
ones nothing covers.

Hybrid split (H2)
-----------------
Rules own the facts: the question inventory is built deterministically,
and every question name the model cites is verified against it - a mapping
to a non-existent question is discarded, never shown. AI owns the
semantics: judging that ``water_source`` + ``treatment_method`` together
inform "access to safe drinking water" is meaning, not matching.

Design
------
One API call per form. Output is a coverage matrix (markdown artefact +
notes) and one advisory ``ai_review`` finding per uncovered objective.
Nothing mutates the form.

Inputs / outputs
----------------
A compiled :class:`~xlsform_studio.models.Questionnaire` and the
objectives text; returns ``(matrix_markdown, notes, findings)`` -
``matrix_markdown`` is "" when the feature didn't run.

Example
-------
>>> AICoverageReviewer(client=None)  # doctest: +SKIP
"""

from __future__ import annotations

import json
from typing import List, Tuple

from ..models import Questionnaire
from ..validation.report_generator import Finding
from .client import AIError, DeepSeekClient
from .prompt_safety import INJECTION_GUARD, frame_untrusted

_SYSTEM_PROMPT = (
    "You are an M&E specialist checking whether a questionnaire covers the "
    "study's objectives. You are given the objectives (one per line) and "
    "the question inventory as json (name, label, type). For EVERY "
    "objective, list the question names that inform it (empty list if "
    "nothing does) and rate coverage: 'full' (adequately measured), "
    "'partial' (touched but incomplete - explain the gap), or 'none'. "
    "Cite only question names that appear in the inventory. Respond ONLY "
    "with a json object of the form {\"coverage\": [{\"objective\": "
    "\"...\", \"questions\": [\"...\"], \"rating\": \"full\", "
    "\"gap\": \"...\"}]}." + INJECTION_GUARD)

_RATING_ICONS = {"full": "✅", "partial": "🟡", "none": "❌"}


class AICoverageReviewer:
    """Map objectives to the questions that inform them via DeepSeek."""

    def __init__(self, client: DeepSeekClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    def review(self, questionnaire: Questionnaire, objectives: str
               ) -> Tuple[str, List[str], List[Finding]]:
        lines = [ln.strip() for ln in (objectives or "").splitlines()
                 if ln.strip()]
        rows = [{"name": q.name, "label": q.label or q.raw_label,
                 "type": q.xlsform_type}
                for q in questionnaire.questions
                if not q.is_structural and q.name]
        if not lines or not rows:
            return "", [], []

        try:
            response = self.client.complete_json(
                _SYSTEM_PROMPT,
                frame_untrusted("Objectives", "\n".join(lines))
                + "Question inventory (json):\n"
                + json.dumps(rows, ensure_ascii=False),
                max_tokens=max(1200, len(lines) * 120))
        except AIError as exc:
            return "", [f"[AI coverage] Skipped: {exc}"], []

        valid_names = {r["name"] for r in rows}
        return self._build(lines, response, valid_names)

    # ------------------------------------------------------------------
    def _build(self, objectives: List[str], response: dict,
               valid_names: set) -> Tuple[str, List[str], List[Finding]]:
        items = response.get("coverage", [])
        if not isinstance(items, list):
            return "", ["[AI coverage] Response was not in the expected "
                        "shape; no matrix produced."], []

        notes: List[str] = []
        findings: List[Finding] = []
        by_objective = {}
        for item in items:
            if isinstance(item, dict) and item.get("objective"):
                by_objective[str(item["objective"]).strip()] = item

        md = ["# Objective Coverage Matrix", "",
              "Question mappings are AI-suggested and each cited question "
              "was verified to exist in the form; coverage judgements are "
              "advisory — confirm them against your analysis plan.", "",
              "| Objective | Coverage | Questions | Gap |",
              "| --- | --- | --- | --- |"]
        uncovered = 0
        for objective in objectives:
            item = by_objective.get(objective, {})
            rating = str(item.get("rating", "none")).lower()
            if rating not in _RATING_ICONS:
                rating = "none"
            cited = [q for q in item.get("questions", [])
                     if isinstance(q, str)]
            invalid = [q for q in cited if q not in valid_names]
            if invalid:
                notes.append(f"[AI coverage] Discarded reference(s) to "
                            f"non-existent question(s) {sorted(invalid)} "
                            f"for objective '{objective}'.")
            questions = [q for q in cited if q in valid_names]
            if not questions and rating != "none":
                rating = "none"           # facts beat the model's rating
            gap = str(item.get("gap", "") or "").strip()
            md.append(f"| {objective} | {_RATING_ICONS[rating]} {rating} | "
                      f"{', '.join(f'`{q}`' for q in questions) or '—'} | "
                      f"{gap or '—'} |")
            if rating != "full":
                uncovered += 1
                findings.append(Finding(
                    "warning", "ai_review",
                    f"Objective not fully covered ({rating}): "
                    f"'{objective}'"
                    + (f" — {gap}" if gap else ""), confidence="heuristic"))

        notes.append(f"[AI coverage] Mapped {len(objectives)} objective(s); "
                    f"{uncovered} not fully covered - see "
                    f"coverage_matrix.md.")
        return "\n".join(md) + "\n", notes, findings
