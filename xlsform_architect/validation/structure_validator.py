"""Structure validator (part of Module 9).

Purpose
-------
Check that the compiled questionnaire has the structural pieces an XLSForm
requires before export:

* at least one survey question
* every question has a type and a name
* select questions reference a choice list
* settings carry a form title and id

Inputs
------
A compiled :class:`~xlsform_architect.models.Questionnaire`.

Outputs
-------
A list of :class:`~xlsform_architect.validation.report_generator.Finding`.

Example
-------
>>> from xlsform_architect.models import Questionnaire, Question
>>> qn = Questionnaire(questions=[Question(name="", xlsform_type="", label="x")])
>>> findings = StructureValidator().validate(qn)
>>> any(f.level == "error" for f in findings)
True
"""

from __future__ import annotations

from typing import List

from ..models import Questionnaire
from .report_generator import Finding


class StructureValidator:
    """Structural completeness checks."""

    def validate(self, questionnaire: Questionnaire) -> List[Finding]:
        findings: List[Finding] = []

        real_questions = [q for q in questionnaire.questions
                          if q.base_type not in ("begin group", "end group")]
        if not real_questions:
            findings.append(Finding("error", "structure",
                                    "The survey sheet has no questions."))

        for q in real_questions:
            ref = q.name or q.raw_label or "<unnamed>"
            if not q.xlsform_type:
                findings.append(Finding("error", "structure",
                                        f"Question '{ref}' has no type.", ref))
            if not q.name:
                findings.append(Finding("error", "structure",
                                        f"Question '{ref}' has no variable name.", ref))
            if not (q.label or q.raw_label):
                findings.append(Finding("warning", "structure",
                                        f"Question '{ref}' has no label.", ref))
            if q.is_select:
                parts = q.xlsform_type.split()
                if len(parts) < 2 or not parts[1]:
                    findings.append(Finding("error", "structure",
                                            f"Select question '{ref}' names no choice list.", ref))

        # Settings.
        if not questionnaire.settings.form_title:
            findings.append(Finding("warning", "structure", "Form title is empty."))
        if not questionnaire.settings.form_id:
            findings.append(Finding("warning", "structure",
                                    "Form id is empty (a default will be generated)."))

        findings.extend(self._check_group_balance(questionnaire))
        return findings

    # ------------------------------------------------------------------
    def _check_group_balance(self, questionnaire: Questionnaire) -> List[Finding]:
        """Verify begin/end group and begin/end repeat markers are balanced.

        A form that opens a group or repeat without closing it (or closes one
        that was never opened) is rejected by ODK/Kobo/SurveyCTO.
        """
        findings: List[Finding] = []
        stack: List[str] = []
        openers = {"begin group": "end group", "begin repeat": "end repeat"}
        closers = {"end group": "begin group", "end repeat": "begin repeat"}

        for q in questionnaire.questions:
            marker = q.base_type
            if marker in openers:
                stack.append(marker)
            elif marker in closers:
                expected_opener = closers[marker]
                if not stack:
                    findings.append(Finding(
                        "error", "structure",
                        f"'{marker}' appears without a matching opener.",
                        q.name))
                elif stack[-1] != expected_opener:
                    findings.append(Finding(
                        "error", "structure",
                        f"'{marker}' does not match the currently open "
                        f"'{stack[-1]}'.", q.name))
                    stack.pop()
                else:
                    stack.pop()

        for unclosed in stack:
            findings.append(Finding(
                "error", "structure",
                f"'{unclosed}' was never closed with '{openers[unclosed]}'."))
        return findings
