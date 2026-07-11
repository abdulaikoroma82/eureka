"""AI indicator mapping engine (optional AI feature; Module A8).

Purpose
-------
Work backwards from the questions to the M&E artefacts around them: infer
the indicators this form can plausibly report, and for each one propose
how it would be computed (numerator/denominator questions), a sensible
aggregation level, and the means of verification. Saves an M&E officer the
first draft of the reporting framework - which questions feed which
indicator is semantics, so it sits in the AI layer.

Design & safety
---------------
One API call per form. Rules own the facts: every question name the model
cites is verified against the deterministic inventory - invalid references
are discarded with a note. Output is a standalone
``indicator_matrix.md`` artefact plus notes; strictly advisory, nothing
mutates the form, and the matrix is labelled as a draft for M&E review.

Inputs / outputs
----------------
A compiled :class:`~xlsform_studio.models.Questionnaire` and the survey
context; returns ``(matrix_markdown, notes)`` - ``""`` when nothing ran.

Example
-------
>>> AIIndicatorMapper(client=None)  # doctest: +SKIP
"""

from __future__ import annotations

import json
from typing import List, Tuple

from ..models import Questionnaire
from .client import AIError, DeepSeekClient
from .prompt_safety import INJECTION_GUARD, frame_untrusted

_SYSTEM_PROMPT = (
    "You are an M&E specialist drafting a reporting framework from a "
    "questionnaire. You are given its question inventory as json (name, "
    "label, type) and optionally the survey's context. Infer the "
    "indicators this form can credibly report. For each: a standard "
    "indicator name; the question names that feed it (numerator and, if "
    "applicable, denominator) - cite ONLY names from the inventory; a "
    "sensible aggregation level (e.g. household, facility, district, "
    "national); and the means of verification (usually this survey's "
    "dataset plus any records mentioned). Prefer recognised indicator "
    "definitions where the questions clearly match one. Only include "
    "indicators the questions actually support; if none, return an empty "
    "list. Respond ONLY with a json object of the form {\"indicators\": "
    "[{\"indicator\": \"...\", \"questions\": [\"...\"], \"aggregation\": "
    "\"...\", \"verification\": \"...\"}]}." + INJECTION_GUARD)


class AIIndicatorMapper:
    """Draft an indicator matrix from the compiled form via DeepSeek."""

    def __init__(self, client: DeepSeekClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    def map(self, questionnaire: Questionnaire,
            survey_context: str = "") -> Tuple[str, List[str]]:
        rows = [{"name": q.name, "label": q.label or q.raw_label,
                 "type": q.xlsform_type}
                for q in questionnaire.questions
                if not q.is_structural and q.name]
        if not rows:
            return "", []

        user_prompt = frame_untrusted("Survey context", survey_context)
        user_prompt += ("Question inventory (json):\n"
                        + json.dumps(rows, ensure_ascii=False))
        try:
            response = self.client.complete_json(
                _SYSTEM_PROMPT, user_prompt,
                max_tokens=max(1200, len(rows) * 40))
        except AIError as exc:
            return "", [f"[AI indicators] Skipped: {exc}"]

        return self._build(response, {r["name"] for r in rows})

    # ------------------------------------------------------------------
    def _build(self, response: dict, valid_names: set
               ) -> Tuple[str, List[str]]:
        items = response.get("indicators", [])
        if not isinstance(items, list):
            return "", ["[AI indicators] Response was not in the expected "
                        "shape; no matrix produced."]
        notes: List[str] = []
        rows: List[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            indicator = str(item.get("indicator", "") or "").strip()
            if not indicator:
                continue
            cited = [q for q in item.get("questions", [])
                     if isinstance(q, str)]
            invalid = [q for q in cited if q not in valid_names]
            if invalid:
                notes.append(f"[AI indicators] Discarded reference(s) to "
                            f"non-existent question(s) {sorted(invalid)} "
                            f"for indicator '{indicator}'.")
            questions = [q for q in cited if q in valid_names]
            if not questions:
                notes.append(f"[AI indicators] Dropped indicator "
                            f"'{indicator}': no valid supporting questions.")
                continue
            rows.append(
                f"| {indicator} | "
                f"{', '.join(f'`{q}`' for q in questions)} | "
                f"{str(item.get('aggregation', '') or '—').strip()} | "
                f"{str(item.get('verification', '') or '—').strip()} |")

        if not rows:
            notes.append("[AI indicators] No indicators could be mapped "
                        "from this form's questions.")
            return "", notes

        md = ["# Indicator Matrix (draft)", "",
              "AI-drafted from the compiled questions; every cited question "
              "was verified to exist. Review definitions, disaggregations "
              "and targets with your M&E plan before adopting.", "",
              "| Indicator | Source questions | Aggregation | "
              "Means of verification |",
              "| --- | --- | --- | --- |"] + rows
        notes.append(f"[AI indicators] Drafted {len(rows)} indicator(s) - "
                    f"see indicator_matrix.md.")
        return "\n".join(md) + "\n", notes
