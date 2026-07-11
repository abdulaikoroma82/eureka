"""AI domain-aware constraint synthesis (optional AI feature).

Purpose
-------
Propose *single-field* range/format constraints for questions the
deterministic constraint engine left unconstrained. The deterministic engine
(:mod:`xlsform_studio.engine.constraint_engine`) only knows the generic,
domain-neutral templates in ``xlsform_rules.yaml`` (age 0-120, percentage
0-100, ...); it cannot know that "temperature" in a *health* survey means
roughly 30-45 °C while in a *weather* survey it means -50-60 °C. A model
reading the question labels - plus an optional user-supplied survey context
("this is a child nutrition survey in Sierra Leone") - can propose sensible
domain bounds.

This is the exact complement of
:class:`~xlsform_studio.ai.constraint_reviewer.AICrossFieldConstraintReviewer`:
that feature only accepts expressions referencing ANOTHER field and rejects
single-field rules; this one only accepts expressions referencing the answer
itself (``.``) and rejects anything mentioning another field. Between the
two, every constraint suggestion lands in exactly one reviewer with the
matching safety gate.

Safety
------
* Only questions with **no existing constraint** are ever sent or touched -
  a constraint set by the deterministic engine (or the user's own document)
  is authoritative and is never modified or combined with here.
* A suggestion is only applied when the expression references **only** the
  current answer (``.``); any ``${...}`` reference is rejected (cross-field
  rules are the other reviewer's job, with its own gate).
* Every accepted expression must pass the deterministic
  :class:`~xlsform_studio.validation.expression_validator.
  ExpressionValidator` syntax check first - AI output is never trusted to be
  well-formed.
* Every applied constraint is logged as an assumption on the question, so
  the human sees exactly which bounds came from AI and can review them.

Inputs
------
A compiled :class:`~xlsform_studio.models.Questionnaire` and an optional
free-text ``survey_context`` describing the survey's domain.

Outputs
-------
The questionnaire, mutated in place for questions that received a validated
constraint, plus the list of notes describing what changed.

Example
-------
>>> AIDomainConstraintSynthesizer(client=None).suggest(Questionnaire())  # doctest: +SKIP
[]
"""

from __future__ import annotations

import json
import re
from typing import List

from ..models import Questionnaire
from ..validation.expression_validator import ExpressionValidator
from .client import AIError, DeepSeekClient
from .prompt_safety import INJECTION_GUARD, frame_untrusted

_REF = re.compile(r"\$\{[^}]*\}")

#: Types for which a range/format constraint is meaningful.
_ELIGIBLE_TYPES = {"integer", "decimal", "date", "datetime", "time", "text"}

_SYSTEM_PROMPT = (
    "You are an XLSForm data-quality expert. You are given survey questions "
    "(name, label, type) that currently have NO validation constraint, plus "
    "an optional description of the survey's domain and setting. Propose an "
    "XLSForm 'constraint' expression for questions where a realistic bound "
    "or format check would catch data-entry errors - for example plausible "
    "ranges for measurements, counts, ages or dates given what the label "
    "and the survey domain say the value means. Use '.' to refer to the "
    "answer itself. NEVER reference another field (no ${...}) - cross-field "
    "rules are handled elsewhere. Prefer generous, defensible bounds that "
    "only exclude physically or logically impossible values; when a label "
    "is too vague to bound safely, omit it entirely. Only propose a change "
    "when confident. Respond ONLY with a json object of the form "
    "{\"suggestions\": [{\"question_name\": \"...\", \"constraint\": \"...\", "
    "\"constraint_message\": \"...\", \"rationale\": \"...\"}]}." + INJECTION_GUARD)


class AIDomainConstraintSynthesizer:
    """Suggest domain-aware single-field constraints via DeepSeek."""

    def __init__(self, client: DeepSeekClient) -> None:
        self.client = client
        self._syntax = ExpressionValidator()

    # ------------------------------------------------------------------
    def suggest(self, questionnaire: Questionnaire,
                survey_context: str = "") -> List[str]:
        candidates = self._unconstrained(questionnaire)
        if not candidates:
            return []

        user_prompt = frame_untrusted("Survey context", survey_context)
        user_prompt += ("Unconstrained questions (json):\n"
                        + json.dumps(candidates, ensure_ascii=False))
        try:
            response = self.client.complete_json(
                _SYSTEM_PROMPT, user_prompt,
                max_tokens=max(1000, len(candidates) * 60))
        except AIError as exc:
            return [f"[AI domain constraints] Skipped: {exc}"]

        eligible = {row["name"] for row in candidates}
        return self._apply(questionnaire, response, eligible)

    # ------------------------------------------------------------------
    def _unconstrained(self, qn: Questionnaire) -> list:
        return [{"name": q.name, "label": q.label or q.raw_label,
                 "type": q.xlsform_type}
                for q in qn.questions
                if not q.is_structural and not q.constraint and q.name
                and q.xlsform_type in _ELIGIBLE_TYPES]

    def _apply(self, qn: Questionnaire, response: dict,
               eligible: set) -> List[str]:
        notes: List[str] = []
        by_name = {q.name: q for q in qn.questions}
        suggestions = response.get("suggestions", [])
        if not isinstance(suggestions, list):
            return ["[AI domain constraints] Response was not in the "
                    "expected shape; no changes applied."]

        for sug in suggestions:
            if not isinstance(sug, dict):
                continue
            name = sug.get("question_name", "")
            expr = (sug.get("constraint") or "").strip()
            message = (sug.get("constraint_message") or "").strip()
            rationale = sug.get("rationale", "")

            target = by_name.get(name)
            if target is None:
                notes.append(f"[AI domain constraints] Rejected suggestion "
                            f"for unknown question '{name}'.")
                continue
            if not expr:
                continue
            if name not in eligible or target.constraint:
                # Only questions we sent (constraint-less at request time)
                # may be touched; an existing constraint is authoritative.
                notes.append(f"[AI domain constraints] Rejected suggestion "
                            f"for '{name}': it already has a constraint, "
                            f"which stays authoritative.")
                continue
            if _REF.search(expr):
                notes.append(f"[AI domain constraints] Rejected suggestion "
                            f"for '{name}': references another field, which "
                            f"is not this feature's job (cross-field "
                            f"constraints are reviewed separately).")
                continue
            error, _ = self._syntax.check(expr)
            if error:
                notes.append(f"[AI domain constraints] Rejected suggestion "
                            f"for '{name}': expression failed syntax "
                            f"validation ({error}).")
                continue

            target.constraint = expr
            if message:
                target.constraint_message = message
            target.add_assumption(
                f"AI-suggested domain constraint "
                f"({rationale or 'no rationale given'}). "
                f"Please review the bounds before deployment.")
            notes.append(f"[AI domain constraints] Applied suggested "
                        f"constraint on '{name}': `{expr}` - please review.")
        return notes
