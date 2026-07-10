"""Validation orchestrator (Module 9).

Purpose
-------
Run every validator over a compiled questionnaire and assemble a single
:class:`ValidationReport`, including the deployment compatibility matrix.

Inputs
------
A compiled :class:`~xlsform_architect.models.Questionnaire`.

Outputs
-------
A :class:`ValidationReport`.

Example
-------
>>> from xlsform_architect.models import Questionnaire, Question
>>> qn = Questionnaire(questions=[Question(name="age", xlsform_type="integer", label="Age")])
>>> Validator().validate(qn).is_valid
True
"""

from __future__ import annotations

from ..models import Questionnaire
from .logic_validator import LogicValidator
from .report_generator import ValidationReport
from .structure_validator import StructureValidator
from .xlsform_validator import XLSFormValidator


class Validator:
    """Aggregate all validators."""

    def __init__(self) -> None:
        self.structure = StructureValidator()
        self.logic = LogicValidator()
        self.xlsform = XLSFormValidator()

    def validate(self, questionnaire: Questionnaire) -> ValidationReport:
        report = ValidationReport()
        report.findings.extend(self.structure.validate(questionnaire))
        report.findings.extend(self.logic.validate(questionnaire))
        report.findings.extend(self.xlsform.validate(questionnaire))
        report.compatibility = self.xlsform.compatibility_matrix(questionnaire)
        return report
