"""XLSForm deployment validator.

Purpose
-------
Verify deployment compatibility with KoboToolbox, SurveyCTO and ODK:

* variable names are valid XML/ODK identifiers
* names are not XLSForm reserved words
* types are recognised XLSForm types
* names respect length limits used by the target platforms
* the ``appearance`` column uses recognised appearance tokens

These are fast, deterministic checks.  For near-authoritative compatibility
the orchestrator additionally runs the pyxform deep check (see
:mod:`~xlsform_studio.validation.pyxform_validator`).

Inputs
------
A compiled :class:`~xlsform_studio.models.Questionnaire`.

Outputs
-------
A list of :class:`~xlsform_studio.validation.report_generator.Finding`,
each tagged with the platform(s) affected.

Example
-------
>>> from xlsform_studio.models import Questionnaire, Question
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

# Types accepted by AT LEAST ONE of ODK / Kobo / SurveyCTO (base keyword).
# Whether the *chosen* target supports a given type is enforced separately by
# the PlatformValidator using knowledge/platforms.yaml.
_VALID_TYPES = {
    # common core
    "integer", "decimal", "text", "select_one", "select_multiple", "note",
    "date", "time", "datetime", "geopoint", "geotrace", "geoshape",
    "image", "audio", "video", "file", "barcode", "calculate",
    "begin group", "end group", "begin repeat", "end repeat",
    "start", "end", "today", "deviceid", "username", "hidden",
    "phonenumber", "simserial", "subscriberid", "email",
    # ODK / Kobo (pyxform engine)
    "acknowledge", "trigger", "range", "rank", "audit", "background-audio",
    "background-geopoint", "start-geopoint", "osm", "csv-external",
    "xml-external", "select_one_from_file", "select_multiple_from_file",
    # SurveyCTO
    "text audit", "audio audit", "sensor_statistic", "sensor_stream",
    "comments", "speed violations count", "speed violations list",
    "speed violations audit", "calculate_here", "caseid",
}

# XLSForm / XForm reserved names that must not be used as variable names.
# Mirrors the reserved set enforced by pyxform (used by ODK & Kobo).
_RESERVED = {
    # XLSForm survey/choices column headers
    "name", "label", "type", "calculation", "constraint", "constraint_message",
    "relevant", "required", "required_message", "choice_filter", "or_other",
    "hint", "default", "appearance", "read_only", "readonly", "repeat_count",
    "media", "parameters", "trigger", "list_name",
    # XForm / instance metadata & literals
    "true", "false", "instance", "meta", "self", "text", "value", "item",
    "itext", "setvalue", "setgeopoint", "start", "end", "today", "now",
}

# Recognised values for the ``appearance`` column (base tokens; some accept a
# parenthesised argument, e.g. ``field-list`` or ``columns-2``).
_VALID_APPEARANCES = {
    "multiline", "url", "numbers", "thousands-sep", "month-year", "year",
    "no-calendar", "week-number", "minimal", "quick", "columns", "columns-pack",
    "no-buttons", "field-list", "table-list", "label", "list-nolabel",
    "compact", "quickcompact", "map", "placement-map", "signature", "draw",
    "annotate", "new", "hidden", "spinner", "horizontal", "horizontal-compact",
    "likert", "autocomplete", "search", "rating", "printer", "bearing",
    "distress", "counter", "compact-1", "image-map", "masked",
}


class XLSFormValidator:
    """Deployment-compatibility checks."""

    def validate(self, questionnaire: Questionnaire) -> List[Finding]:
        findings: List[Finding] = []
        targets = ", ".join(t.upper() for t in DEPLOYMENT_TARGETS)

        for q in questionnaire.questions:
            base = q.base_type
            if base in ("begin group", "end group", "begin repeat", "end repeat"):
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

            # Appearance recognised?
            findings.extend(self._check_appearance(q))

        return findings

    # ------------------------------------------------------------------
    @staticmethod
    def _check_appearance(q) -> List[Finding]:
        appearance = (q.appearance or "").strip()
        if not appearance:
            return []
        findings: List[Finding] = []
        for token in appearance.split():
            # Strip any parenthesised argument, e.g. "columns-2" stays, but
            # "field-list(...)" -> "field-list".
            base = token.split("(", 1)[0].strip()
            # Allow the "columns-N" family with a numeric suffix.
            core = re.sub(r"-\d+$", "", base)
            if base and base not in _VALID_APPEARANCES and core not in _VALID_APPEARANCES:
                findings.append(Finding(
                    "warning", "deployment",
                    f"Appearance '{token}' on '{q.name}' is not a standard "
                    f"appearance; check it is supported on your target platform.",
                    q.name))
        return findings

    # ------------------------------------------------------------------
    def compatibility_matrix(self, questionnaire: Questionnaire) -> dict:
        """Return a per-platform pass/fail summary for the QA report."""
        errors = [f for f in self.validate(questionnaire) if f.level == "error"]
        ok = not errors
        return {target: ok for target in DEPLOYMENT_TARGETS}
