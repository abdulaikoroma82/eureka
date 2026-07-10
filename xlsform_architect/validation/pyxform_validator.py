"""Deep XLSForm validator via pyxform (part of Module 9).

Purpose
-------
Run the *actual* engine that ODK and KoboToolbox use - `pyxform` - over the
generated workbook.  pyxform converts the XLSForm to an ODK XForm (XML); if
that conversion succeeds the form is compatible with the ODK / Kobo toolchain
at a near-authoritative level, catching problems the lightweight checks do
not (invalid XPath in relevant/constraint/calculation, group/repeat nesting,
cascading-select issues, and more).

The conversion runs **entirely offline** and does not require Java (that is
only needed for the optional ODK Validate step, which we deliberately skip to
keep the tool self-contained).

Inputs
------
A compiled :class:`~xlsform_architect.models.Questionnaire`.

Outputs
-------
A list of :class:`~xlsform_architect.validation.report_generator.Finding`.
An import/convert failure becomes a single ``error`` finding; pyxform
warnings become ``warning`` findings.

Availability
------------
If pyxform is not installed, :attr:`available` is ``False`` and
:meth:`validate` returns an ``info`` finding rather than failing, so the rest
of the pipeline is unaffected.

Example
-------
>>> v = PyxformValidator()
>>> v.available  # doctest: +SKIP
True
"""

from __future__ import annotations

from typing import List

from ..models import Questionnaire
from ..xlsform.exporter import XLSFormExporter
from .report_generator import Finding


class PyxformValidator:
    """Near-authoritative ODK/Kobo compatibility check using pyxform."""

    def __init__(self) -> None:
        self.exporter = XLSFormExporter()
        self._convert = None
        self._error_types: tuple = (Exception,)
        try:
            from pyxform.xls2xform import convert
            from pyxform.errors import PyXFormError, PyXFormReadError, ValidationError
            self._convert = convert
            self._error_types = (PyXFormError, PyXFormReadError, ValidationError)
        except Exception:  # pragma: no cover - pyxform optional
            self._convert = None

    @property
    def available(self) -> bool:
        return self._convert is not None

    # ------------------------------------------------------------------
    def validate(self, questionnaire: Questionnaire) -> List[Finding]:
        if not self.available:
            return [Finding(
                "info", "deployment",
                "Deep validation skipped: pyxform is not installed "
                "(pip install pyxform) - relying on the standard checks.")]

        findings: List[Finding] = []
        try:
            xls_bytes = self.exporter.export_bytes(questionnaire)
        except Exception as exc:  # pragma: no cover - defensive
            return [Finding("error", "deployment",
                            f"Could not build the workbook for deep validation: {exc}")]

        warnings: List[str] = []
        try:
            self._convert(xls_bytes, warnings=warnings, file_type=".xlsx")
        except self._error_types as exc:
            findings.append(Finding(
                "error", "deployment",
                f"pyxform (ODK/Kobo engine) rejected the form: {self._clean(exc)}"))
            return findings
        except Exception as exc:  # unexpected pyxform failure
            findings.append(Finding(
                "warning", "deployment",
                f"Deep validation could not complete: {self._clean(exc)}"))
            return findings

        # Conversion succeeded: surface any advisory warnings.
        for w in warnings:
            findings.append(Finding("warning", "deployment",
                                    f"pyxform warning: {self._clean(w)}"))
        if not findings:
            findings.append(Finding(
                "info", "deployment",
                "Deep validation passed: pyxform converted the form to a valid "
                "ODK XForm (ODK/Kobo compatible)."))
        return findings

    # ------------------------------------------------------------------
    @staticmethod
    def _clean(obj) -> str:
        text = str(obj).strip().replace("\n", " ")
        return (text[:400] + "...") if len(text) > 400 else text
