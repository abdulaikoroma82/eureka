"""XLSForm deployment validator (part of Module 9).

Purpose
-------
Verify deployment compatibility with KoboToolbox, SurveyCTO and ODK:

* variable names are valid XML/ODK identifiers
* names are not XLSForm reserved words
* types are recognised XLSForm types
* names respect length limits used by the target platforms

Inputs
------
A compiled :class:`~xlsform_architect.models.Questionnaire`.

Outputs
-------
A list of :class:`~xlsform_architect.validation.report_generator.Finding`,
each tagged with the platform(s) affected.

Example
-------
>>> from xlsform_architect.models import Questionnaire, Question
>>> qn = Questionnaire(questions=[Question(name="1bad", xlsform_type="integer", label="x")])
>>> any(f.level == "error" for f in XLSFormValidator().validate(qn))
True
"""

from __future__ import annotations

import re
from typing import List

from ..app.config import DEPLOYMENT_TARGETS
from ..models import Questionnaire
from .report_generator import Finding

_VALID_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Types accepted across ODK/Kobo/SurveyCTO (base keyword).
_VALID_TYPES = {
    "integer", "decimal", "text", "select_one", "select_multiple", "note",
    "date", "time", "datetime", "geopoint", "geotrace", "geoshape",
    "image", "audio", "video", "file", "barcode", "calculate", "acknowledge",
    "range", "begin group", "end group", "begin repeat", "end repeat",
    "start", "end", "today", "deviceid", "username", "hidden",
}

# XLSForm / XML reserved names that must not be used as variable names.
_RESERVED = {"name", "label", "type", "calculation", "constraint", "relevant",
             "required", "choice_filter", "or_other", "true", "false"}


class XLSFormValidator:
    """Deployment-compatibility checks."""

    def validate(self, questionnaire: Questionnaire) -> List[Finding]:
        findings: List[Finding] = []
        targets = ", ".join(t.upper() for t in DEPLOYMENT_TARGETS)

        for q in questionnaire.questions:
            base = q.base_type
            if base in ("begin group", "end group"):
                continue

            # Type recognised?
            if base and base not in _VALID_TYPES:
                findings.append(Finding("error", "deployment",
                                        f"Unknown XLSForm type '{q.xlsform_type}' on '{q.name}' "
                                        f"(not accepted by {targets}).", q.name))

            if not q.name:
                continue

            # Valid identifier?
            if not _VALID_NAME.match(q.name):
                findings.append(Finding("error", "deployment",
                                        f"Variable name '{q.name}' is not a valid ODK/XML identifier.",
                                        q.name))
            # Reserved word?
            if q.name.lower() in _RESERVED:
                findings.append(Finding("error", "deployment",
                                        f"Variable name '{q.name}' is a reserved XLSForm keyword.",
                                        q.name))
            # Length (SurveyCTO/ODK are comfortable well under 64).
            if len(q.name) > 64:
                findings.append(Finding("warning", "deployment",
                                        f"Variable name '{q.name}' exceeds 64 characters.", q.name))

        return findings

    # ------------------------------------------------------------------
    def compatibility_matrix(self, questionnaire: Questionnaire) -> dict:
        """Return a per-platform pass/fail summary for the QA report."""
        errors = [f for f in self.validate(questionnaire) if f.level == "error"]
        ok = not errors
        return {target: ok for target in DEPLOYMENT_TARGETS}
