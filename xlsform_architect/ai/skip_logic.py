"""AI skip-logic inversion (optional AI feature).

Purpose
-------
Resolve "skip to question N" instructions that the deterministic logic
engine (:mod:`xlsform_architect.engine.logic_engine`) cannot safely invert.
XLSForm expresses skips as ``relevant`` conditions on the questions being
*shown*, not as jumps - turning "if no, skip to Q20" into the correct
``relevant`` expression on Q20 (and everything between the skip source and
target) requires understanding the whole form's structure, which is exactly
the kind of multi-step reasoning a rule engine cannot do reliably but a
language model can attempt.

Design
------
One API call per form: the whole compiled survey (name, label, type, section,
position) plus every unresolved skip instruction is sent together, since the
model needs the full question list to identify the jump target. The model
returns proposed ``relevant`` expressions referencing ``${question_name}``.

Safety
------
Every suggestion is validated before being applied: the target question must
exist, and every ``${...}`` reference inside the proposed expression must
name a real question. Suggestions that fail validation are rejected and
reported rather than written into the form - the tool never lets unverified
AI output become authoritative constraint/logic text.

Inputs
------
A compiled :class:`~xlsform_architect.models.Questionnaire` (whose questions
carry a "Skip pattern detected" assumption where the deterministic engine
gave up).

Outputs
-------
The questionnaire, mutated in place: validated ``relevant`` expressions are
applied to the target question(s), each with an assumption note flagging it
as an AI suggestion that should be reviewed. Returns the list of notes.

Example
-------
>>> resolver = AISkipLogicResolver(client=None)
>>> resolver.resolve(Questionnaire())  # doctest: +SKIP
[]
"""

from __future__ import annotations

import re
from typing import Dict, List

from ..models import Questionnaire
from .client import AIError, DeepSeekClient

_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

_SYSTEM_PROMPT = (
    "You are an XLSForm logic expert. You are given a compiled survey (an "
    "ordered list of questions with name, label, type and section) and a "
    "list of unresolved 'skip to' instructions written in plain English. "
    "XLSForm has no jump/goto construct: a skip is implemented by adding a "
    "'relevant' condition (XPath-like, referencing other fields as "
    "${field_name}) to the question(s) that should be SKIPPED OVER, so they "
    "are hidden instead of jumped past. "
    "For each skip instruction, identify which question is being skipped "
    "FROM and which question(s) should become conditionally hidden, then "
    "propose a 'relevant' expression for each affected question using only "
    "field names that appear in the provided list. Only propose a change "
    "when you are confident; omit anything ambiguous. "
    "Respond ONLY with a json object of the form "
    "{\"suggestions\": [{\"question_name\": \"...\", \"relevant\": \"...\", "
    "\"rationale\": \"...\"}]}.")


class AISkipLogicResolver:
    """Resolve unresolved skip-to instructions via DeepSeek, with validation."""

    def __init__(self, client: DeepSeekClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    def resolve(self, questionnaire: Questionnaire) -> List[str]:
        pending = self._pending_skips(questionnaire)
        if not pending:
            return []

        survey = self._survey_summary(questionnaire)
        valid_names = {q.name for q in questionnaire.questions if q.name}

        try:
            response = self._request(survey, pending)
        except AIError as exc:
            return [f"[AI skip-logic] Skipped ({len(pending)} instruction(s) "
                    f"still need manual review): {exc}"]

        return self._apply_suggestions(questionnaire, response, valid_names)

    # ------------------------------------------------------------------
    def _pending_skips(self, qn: Questionnaire) -> List[Dict[str, str]]:
        pending = []
        for q in qn.questions:
            if q.is_structural:
                continue
            for note in q.assumptions:
                if "Skip pattern detected" in note:
                    pending.append({"from_question": q.name, "instruction": q.logic})
        return pending

    def _survey_summary(self, qn: Questionnaire) -> List[Dict[str, str]]:
        return [
            {"position": i, "name": q.name, "label": q.label or q.raw_label,
             "type": q.xlsform_type, "section": q.section}
            for i, q in enumerate(qn.questions) if not q.is_structural
        ]

    def _request(self, survey, pending) -> dict:
        user_prompt = (
            "Survey (json):\n" + self._to_json(survey) +
            "\n\nUnresolved skip instructions (json):\n" + self._to_json(pending))
        return self.client.complete_json(
            _SYSTEM_PROMPT, user_prompt,
            max_tokens=max(1500, len(survey) * 40 + len(pending) * 200))

    @staticmethod
    def _to_json(obj) -> str:
        import json
        return json.dumps(obj, ensure_ascii=False)

    # ------------------------------------------------------------------
    def _apply_suggestions(self, qn: Questionnaire, response: dict,
                           valid_names: set) -> List[str]:
        notes: List[str] = []
        by_name = {q.name: q for q in qn.questions}
        suggestions = response.get("suggestions", [])
        if not isinstance(suggestions, list):
            return ["[AI skip-logic] Response was not in the expected shape; "
                    "no changes applied."]

        for sug in suggestions:
            if not isinstance(sug, dict):
                continue
            name = sug.get("question_name", "")
            expr = (sug.get("relevant") or "").strip()
            rationale = sug.get("rationale", "")

            target = by_name.get(name)
            if target is None:
                notes.append(f"[AI skip-logic] Rejected suggestion for unknown "
                            f"question '{name}'.")
                continue
            if not expr:
                continue
            refs = set(_REF.findall(expr))
            unknown = refs - valid_names
            if unknown:
                notes.append(f"[AI skip-logic] Rejected suggestion for "
                            f"'{name}': references unknown field(s) "
                            f"{sorted(unknown)}.")
                continue
            if target.relevant:
                notes.append(f"[AI skip-logic] '{name}' already has a "
                            f"relevant condition; AI suggestion not applied "
                            f"(review manually: `{expr}`).")
                continue

            target.relevant = expr
            target.add_assumption(
                f"AI-suggested relevant condition from skip logic ({rationale or 'no rationale given'}). "
                f"Please review before deployment.")
            notes.append(f"[AI skip-logic] Applied suggested relevant on "
                        f"'{name}': `{expr}` - please review.")
        return notes
