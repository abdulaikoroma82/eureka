"""AI quality review (optional AI feature).

Purpose
-------
A final, holistic read of the compiled form that catches problems
structural/logic validators cannot see because they only ever check one rule
at a time. Three kinds of issue, all advisory-only:

* **Semantic contradictions** - e.g. a constraint that contradicts its own
  label (age constraint 0-120 on a field labelled "age in months"), a
  relevant condition that can never be true, or a question whose type
  doesn't match what it is clearly asking for.
* **Naming/label clarity** - a variable name or label that would confuse
  someone reading the exported data later (e.g. a name so abbreviated its
  meaning is lost). This is commentary only: the rule engine permanently
  owns the actual ``name`` and ``label`` values (naming must stay
  deterministic and stable - see the README) - this pass never renames
  anything, it only surfaces a suggestion for a human to act on.
* **Respondent experience** - problems that surface in the field rather
  than in the data: a question phrased so ambiguously respondents will
  interpret it differently; a select_multiple whose options are mutually
  exclusive; answer-option styles that flip between questions (Yes/No here,
  True/False there); two questions asking essentially the same thing; a
  skip chain whose combined conditions make a question unreachable or
  nonsensical for the people who will actually see it.

Design
------
One API call per form: the entire compiled survey (names, labels, types,
constraints, relevant expressions, choice lists) is sent together, since
these are inherently cross-question checks. Findings come back as structured
JSON and are converted into the same :class:`Finding` type the deterministic
validators use, tagged with category ``"ai_review"`` so they are clearly
distinguishable as advisory rather than authoritative.

Findings from this pass are always capped at ``warning`` level (never
``error``) - the AI review is a second pair of eyes, not a gate. It cannot
block export the way a real structural error does, and it never mutates the
questionnaire (unlike the other AI features) - it only ever returns
findings for a human to read.

Inputs
------
A compiled :class:`~xlsform_architect.models.Questionnaire`, plus an
optional free-text ``survey_context`` describing the survey's domain and
setting, which grounds the review (what counts as a sensible option list or
a plausible bound depends on what the survey is about).

Outputs
-------
A list of :class:`~xlsform_architect.validation.report_generator.Finding`.

Example
-------
>>> AIQualityReviewer(client=None).review(Questionnaire())  # doctest: +SKIP
[]
"""

from __future__ import annotations

import json
from typing import List

from ..models import Questionnaire
from ..validation.report_generator import Finding
from .client import AIError, DeepSeekClient

_SYSTEM_PROMPT = (
    "You are a meticulous XLSForm quality reviewer. You are given a compiled "
    "survey as json: each question's name, label, type, constraint, "
    "constraint_message, relevant condition, calculation and choice list. "
    "Look for three kinds of issue, all ADVISORY ONLY - you are never asked "
    "to change anything, only to flag it for a human to review: "
    "(1) SEMANTIC problems simple rule checks would miss, such as a "
    "constraint or type that contradicts what the label is asking for; a "
    "relevant condition that references the wrong field or looks like it "
    "can never be satisfied; a calculation that doesn't match its inputs; a "
    "choice list whose options look incomplete or inconsistent for the "
    "question asked. "
    "(2) NAMING/LABEL CLARITY - a variable name or label so unclear, "
    "ambiguous, or inconsistently abbreviated that someone reading the "
    "exported data later would struggle to understand it. Only flag names "
    "that are genuinely confusing, not just short. "
    "(3) RESPONDENT EXPERIENCE - problems that surface during interviews "
    "rather than in the data: a question phrased so ambiguously that "
    "respondents will interpret it differently; a select_multiple whose "
    "options are mutually exclusive; answer-option styles that switch "
    "between questions asking the same kind of thing (e.g. Yes/No on one, "
    "True/False on another); two questions that ask essentially the same "
    "thing; a chain of relevant conditions that makes a question "
    "unreachable or nonsensical for the respondents who would see it. "
    "Do NOT repeat purely structural issues like missing names or duplicate "
    "names - assume those are already checked elsewhere. Only report "
    "genuine, explainable concerns; if the form looks fine, return an empty "
    "list. Respond ONLY with a json object of the form "
    "{\"findings\": [{\"question_name\": \"...\", \"issue\": \"...\", "
    "\"explanation\": \"...\"}]}.")


class AIQualityReviewer:
    """Holistic semantic review of a compiled form via DeepSeek."""

    def __init__(self, client: DeepSeekClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    def review(self, questionnaire: Questionnaire,
               survey_context: str = "") -> List[Finding]:
        rows = self._survey_summary(questionnaire)
        if not rows:
            return []

        user_prompt = ""
        if survey_context.strip():
            user_prompt += f"Survey context: {survey_context.strip()}\n"
        user_prompt += "Survey (json):\n" + json.dumps(rows, ensure_ascii=False)
        try:
            response = self.client.complete_json(
                _SYSTEM_PROMPT, user_prompt,
                max_tokens=max(1500, len(rows) * 60))
        except AIError as exc:
            return [Finding("info", "ai_review",
                            f"AI quality review could not run: {exc}")]

        return self._to_findings(response)

    # ------------------------------------------------------------------
    def _survey_summary(self, qn: Questionnaire) -> list:
        rows = []
        for q in qn.questions:
            if q.is_structural:
                continue
            list_name = ""
            choices = []
            if q.references_choices:
                parts = q.xlsform_type.split()
                list_name = parts[1] if len(parts) >= 2 else q.list_name
                cl = qn.choice_lists.get(list_name)
                if cl:
                    choices = [c.label for c in cl.choices]
            rows.append({
                "name": q.name, "label": q.label or q.raw_label,
                "type": q.xlsform_type, "constraint": q.constraint,
                "constraint_message": q.constraint_message,
                "relevant": q.relevant, "calculation": q.calculation,
                "choices": choices,
            })
        return rows

    def _to_findings(self, response: dict) -> List[Finding]:
        findings: List[Finding] = []
        items = response.get("findings", [])
        if not isinstance(items, list):
            return [Finding("info", "ai_review",
                            "AI review response was not in the expected shape.")]

        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("question_name", "")
            issue = item.get("issue", "").strip()
            explanation = item.get("explanation", "").strip()
            if not issue:
                continue
            message = issue if not explanation else f"{issue} — {explanation}"
            findings.append(Finding("warning", "ai_review", message, name))
        return findings
