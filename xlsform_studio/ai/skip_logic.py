"""AI logic fallback: skip-jumps and unparseable conditions (optional AI feature).

Purpose
-------
Resolve the two ways the deterministic logic engine
(:mod:`xlsform_studio.engine.logic_engine`) gives up on a piece of plain-
English logic, leaving ``relevant`` empty:

1. **"Skip to question N" jumps.** XLSForm has no jump/goto construct - a
   skip is expressed as a ``relevant`` condition on the question(s) being
   skipped OVER, not the one carrying the instruction. Inverting the jump
   requires knowing the whole form's structure to find the target question -
   multi-step reasoning a rule engine cannot do reliably.
2. **Complex conditions the atom-by-atom compiler couldn't parse** (e.g.
   unanticipated phrasing of a compound rule). Unlike a skip, this condition
   usually belongs on the *same* question that carries the instruction.

Both cases are sent to the model together in one call, since the model needs
the same context (the whole compiled survey) for either kind, and the same
suggestion schema (question name + relevant expression) naturally covers
both - the model decides whether the condition belongs on the source
question or a downstream one it identifies as the skip target.

Design
------
One API call per form: the whole compiled survey (name, label, type, section,
position) plus every unresolved instruction is sent together.

Safety
------
Every suggestion is validated before being applied: the target question must
exist, every ``${...}`` reference inside the proposed expression must name a
real question, and an existing non-empty ``relevant`` is never overwritten.
Suggestions that fail validation are rejected and reported rather than
written into the form - the tool never lets unverified AI output become
authoritative logic text.

Inputs
------
A compiled :class:`~xlsform_studio.models.Questionnaire` (whose questions
carry a "Skip pattern detected" or "could not be auto-compiled" assumption
where the deterministic engine gave up).

Outputs
-------
The questionnaire, mutated in place: validated ``relevant`` expressions are
applied, each with an assumption note flagging it as an AI suggestion that
should be reviewed. Returns the list of notes.

Example
-------
>>> resolver = AISkipLogicResolver(client=None)
>>> resolver.resolve(Questionnaire())  # doctest: +SKIP
[]
"""

from __future__ import annotations

from typing import Dict, List

from ..models import Questionnaire, REF_PATTERN
from .client import AIError, DeepSeekClient

_REF = REF_PATTERN

_SYSTEM_PROMPT = (
    "You are an XLSForm logic expert. You are given a compiled survey (an "
    "ordered list of questions with name, label, type and section) and a "
    "list of instructions the automated compiler could not resolve. Each "
    "instruction is one of two kinds, given in its 'kind' field: "
    "'skip' - a 'skip to question N' style jump. XLSForm has no jump/goto "
    "construct: implement it by adding a 'relevant' condition to the "
    "question(s) that should be SKIPPED OVER (hidden), not the one carrying "
    "the instruction - identify the skip target from the survey order. "
    "'condition' - a plain-English conditional phrase attached to a "
    "specific question that the compiler's pattern matching could not "
    "parse. Usually the resulting 'relevant' expression belongs on THAT "
    "SAME question (use its own name as question_name), unless the wording "
    "clearly describes skipping past OTHER questions, in which case treat "
    "it like a skip. "
    "For every instruction, propose a 'relevant' expression (XPath-like, "
    "referencing other fields as ${field_name}) using only field names that "
    "appear in the provided survey. Only propose a change when you are "
    "confident; omit anything ambiguous. Rate each proposal's confidence "
    "as 'high' (the instruction has exactly one sensible reading) or "
    "'medium' (a reasonable reading, but a human should double-check). "
    "Respond ONLY with a json object of the form "
    "{\"suggestions\": [{\"question_name\": \"...\", \"relevant\": \"...\", "
    "\"confidence\": \"high\", \"rationale\": \"...\"}]}.")


class AISkipLogicResolver:
    """Resolve unresolved skip/condition logic via DeepSeek, with validation."""

    def __init__(self, client: DeepSeekClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    def resolve(self, questionnaire: Questionnaire) -> List[str]:
        pending = self._pending_logic(questionnaire)
        if not pending:
            return []

        survey = self._survey_summary(questionnaire)
        valid_names = {q.name for q in questionnaire.questions if q.name}

        try:
            response = self._request(survey, pending)
        except AIError as exc:
            return [f"[AI logic] Skipped ({len(pending)} instruction(s) "
                    f"still need manual review): {exc}"]

        return self._apply_suggestions(questionnaire, response, valid_names)

    # ------------------------------------------------------------------
    def _pending_logic(self, qn: Questionnaire) -> List[Dict[str, str]]:
        """Every question the deterministic engine gave up on, by kind."""
        pending = []
        for q in qn.questions:
            if q.is_structural:
                continue
            for note in q.assumptions:
                if "Skip pattern detected" in note:
                    pending.append({"kind": "skip", "from_question": q.name,
                                    "instruction": q.logic})
                elif "could not be auto-compiled" in note:
                    pending.append({"kind": "condition", "from_question": q.name,
                                    "instruction": q.logic})
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
            "\n\nUnresolved instructions (json):\n" + self._to_json(pending))
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
            return ["[AI logic] Response was not in the expected shape; "
                    "no changes applied."]

        for sug in suggestions:
            if not isinstance(sug, dict):
                continue
            name = sug.get("question_name", "")
            expr = (sug.get("relevant") or "").strip()
            rationale = sug.get("rationale", "")
            confidence = str(sug.get("confidence") or "").strip().lower()
            conf_tag = f", confidence: {confidence}" if confidence else ""

            target = by_name.get(name)
            if target is None:
                notes.append(f"[AI logic] Rejected suggestion for unknown "
                            f"question '{name}'.")
                continue
            if not expr:
                continue
            refs = set(_REF.findall(expr))
            unknown = refs - valid_names
            if unknown:
                notes.append(f"[AI logic] Rejected suggestion for "
                            f"'{name}': references unknown field(s) "
                            f"{sorted(unknown)}.")
                continue
            if target.relevant:
                notes.append(f"[AI logic] '{name}' already has a "
                            f"relevant condition; AI suggestion not applied "
                            f"(review manually: `{expr}`).")
                continue

            target.relevant = expr
            target.add_assumption(
                f"AI-suggested relevant condition "
                f"({rationale or 'no rationale given'}{conf_tag}). "
                f"Please review before deployment.")
            notes.append(f"[AI logic] Applied suggested relevant on "
                        f"'{name}': `{expr}`{conf_tag} - please review.")
        return notes
