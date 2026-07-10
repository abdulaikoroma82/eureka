"""Validation orchestrator (Module 9).

Purpose
-------
Run every validator over a compiled questionnaire and assemble a single
:class:`ValidationReport`, including the honest per-platform compatibility
matrix.

Runs, in order:
  1. Structure checks (sheets, types, names, group/repeat balance)
  2. Logic checks (duplicate names, broken references, choice lists)
  3. Generic deployment checks (identifiers, reserved words, appearance)
  4. Platform checks - the standards of the CHOSEN target (Kobo / SurveyCTO /
     ODK) from ``knowledge/platforms.yaml``: supported types, naming rules,
     settings recommendations.
  5. Deep check via pyxform (the ODK/Kobo engine) when available and enabled.

The compatibility matrix is computed per platform: a form using ``rank`` is
marked compatible with ODK/Kobo but incompatible with SurveyCTO.

Inputs
------
A compiled :class:`~xlsform_architect.models.Questionnaire` and optionally a
``target`` platform key.

Outputs
-------
A :class:`ValidationReport`.

Example
-------
>>> from xlsform_architect.models import Questionnaire, Question
>>> qn = Questionnaire(questions=[Question(name="age", xlsform_type="integer", label="Age")])
>>> Validator().validate(qn, target="kobo").is_valid
True
"""

from __future__ import annotations

from typing import Optional

from ..engine.knowledge_base import KnowledgeBase
from ..models import Questionnaire
from .logic_validator import LogicValidator
from .platform_validator import PlatformValidator
from .pyxform_validator import PyxformValidator
from .report_generator import ValidationReport
from .structure_validator import StructureValidator
from .xlsform_validator import XLSFormValidator


class Validator:
    """Aggregate all validators."""

    def __init__(self, deep: bool = True,
                 knowledge: Optional[KnowledgeBase] = None) -> None:
        #: When True (default), also run the pyxform deep check if installed.
        self.deep = deep
        self.kb = knowledge or KnowledgeBase.load()
        self.structure = StructureValidator()
        self.logic = LogicValidator()
        self.xlsform = XLSFormValidator()
        self.platform = PlatformValidator(self.kb)
        self.pyxform = PyxformValidator()

    def validate(self, questionnaire: Questionnaire,
                 target: Optional[str] = None,
                 deep: Optional[bool] = None) -> ValidationReport:
        run_deep = self.deep if deep is None else deep
        report = ValidationReport(target=target or "")
        report.findings.extend(self.structure.validate(questionnaire))
        report.findings.extend(self.logic.validate(questionnaire))
        report.findings.extend(self.xlsform.validate(questionnaire))

        # Standards of the chosen platform.
        if target:
            report.findings.extend(self.platform.validate(questionnaire, target))

        # Deep (pyxform) check.
        deep_error = False
        if run_deep:
            deep_findings = self.pyxform.validate(questionnaire)
            report.findings.extend(deep_findings)
            report.deep_ran = self.pyxform.available
            deep_error = any(f.level == "error" for f in deep_findings)

        # Per-platform compatibility: generic validity AND that platform's
        # own standards.  A pyxform hard failure (broken reference, bad
        # structure) breaks the form everywhere, so it zeroes the matrix.
        generic_errors = [f for f in report.findings
                          if f.level == "error" and f.category != "platform"]
        generally_valid = not generic_errors and not deep_error
        report.compatibility = self.platform.matrix(questionnaire, generally_valid)
        return report
