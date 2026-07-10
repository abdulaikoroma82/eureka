"""Settings sheet builder (part of Module 4).

Purpose
-------
Produce the single-row XLSForm ``settings`` sheet, filling in a form id and a
timestamp-based version when the caller did not supply them.

Inputs
------
A :class:`~xlsform_architect.models.Questionnaire` (its ``settings``).

Outputs
-------
A one-element list containing the settings row dict.

Example
-------
>>> from xlsform_architect.models import Questionnaire, FormSettings
>>> qn = Questionnaire(settings=FormSettings(form_title="OTP Register"))
>>> row = SettingsBuilder().build(qn)[0]
>>> row["form_title"]
'OTP Register'
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Dict, List

from ..app.config import CONFIG, SETTINGS_COLUMNS
from ..models import Questionnaire

_NON_WORD = re.compile(r"[^0-9a-zA-Z]+")


class SettingsBuilder:
    """Build the settings sheet row."""

    def build(self, questionnaire: Questionnaire) -> List[Dict[str, str]]:
        s = questionnaire.settings
        form_id = s.form_id or self._slug(s.form_title) or "untitled_form"
        version = s.version or _dt.datetime.now().strftime(CONFIG.default_version_format)

        row = {col: "" for col in SETTINGS_COLUMNS}
        row["form_title"] = s.form_title or "Untitled Form"
        row["form_id"] = form_id
        row["version"] = version
        row["default_language"] = s.default_language
        row["style"] = s.style
        # Persist resolved values back so downstream artefacts stay consistent.
        s.form_id = form_id
        s.version = version
        return [row]

    @staticmethod
    def _slug(text: str) -> str:
        return _NON_WORD.sub("_", (text or "").strip().lower()).strip("_")[:60]
