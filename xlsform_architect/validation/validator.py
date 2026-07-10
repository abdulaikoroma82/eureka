"""Validation orchestrator (Module 9).

Purpose
-------
Run every validator over a compiled questionnaire and assemble a single
:class:`ValidationReport`, including the deployment compatibility matrix.

Runs, in order:
  1. Structure checks (sheets, types, names, group/repeat balance)
  2. Logic checks (duplicate names, broken references, choice lists)
  3. Deployment checks (identifiers, reserved words, types, appearance)
  4. Deep check via pyxform - the engine ODK/Kobo use - when available and
     enabled (``deep=True``).  This converts the form to an ODK XForm offline,
     catching XPath and structural problems the lightweight checks cannot.

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
from .pyxform_validator import PyxformValidator
from .report_generator import ValidationReport
from .structure_validator import StructureValidator
from .xlsform_validator import XLSFormValidator


class Validator:
    """Aggregate all validators."""

    def __init__(self, deep: bool = True) -> None:
        #: When True (default), also run the pyxform deep check if installed.
        self.deep = deep
        self.structure = StructureValidator()
        self.logic = LogicValidator()
        self.xlsform = XLSFormValidator()
        self.pyxform = PyxformValidator()

    def validate(self, questionnaire: Questionnaire,
                 deep: bool | None = None) -> ValidationReport:
        run_deep = self.deep if deep is None else deep
        report = ValidationReport()
        report.findings.extend(self.structure.validate(questionnaire))
        report.findings.extend(self.logic.validate(questionnaire))
        report.findings.extend(self.xlsform.validate(questionnaire))
        report.compatibility = self.xlsform.compatibility_matrix(questionnaire)

        if run_deep:
            deep_findings = self.pyxform.validate(questionnaire)
            report.findings.extend(deep_findings)
            # A pyxform rejection means the form is NOT deployable anywhere.
            report.deep_ran = self.pyxform.available
            if any(f.level == "error" for f in deep_findings):
                report.compatibility = {k: False for k in report.compatibility}
        return report
