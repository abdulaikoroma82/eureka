"""Survey sheet builder (part of Module 4).

Purpose
-------
Turn the enriched questions of a :class:`Questionnaire` into rows for the
XLSForm ``survey`` sheet, inserting ``begin group`` / ``end group`` markers
for sections.

Inputs
------
A compiled :class:`~xlsform_architect.models.Questionnaire`.

Outputs
-------
A list of ``dict`` rows keyed by the survey columns defined in
:data:`xlsform_architect.app.config.SURVEY_COLUMNS`.

Example
-------
>>> from xlsform_architect.models import Questionnaire, Question
>>> qn = Questionnaire(questions=[Question(name="age", xlsform_type="integer",
...                                         label="Age")])
>>> rows = SurveyBuilder().build(qn)
>>> rows[0]["type"], rows[0]["name"]
('integer', 'age')
"""

from __future__ import annotations

import re
from typing import Dict, List

from ..app.config import SURVEY_COLUMNS
from ..models import Question, Questionnaire

_NON_WORD = re.compile(r"[^0-9a-zA-Z]+")


class SurveyBuilder:
    """Build the survey sheet rows."""

    def build(self, questionnaire: Questionnaire) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        current_section = None
        current_group = ""
        used_groups: set = set()

        for q in questionnaire.questions:
            section = (q.section or "").strip()
            if section != current_section:
                if current_section:
                    rows.append(self._group_row("end group", current_group))
                if section:
                    current_group = self._unique_group_name(section, used_groups)
                    used_groups.add(current_group)
                    rows.append(self._group_row("begin group", current_group, section))
                current_section = section
            rows.append(self._question_row(q))

        if current_section:
            rows.append(self._group_row("end group", current_group))
        return rows

    # ------------------------------------------------------------------
    def _question_row(self, q: Question) -> Dict[str, str]:
        row = {col: "" for col in SURVEY_COLUMNS}
        row["type"] = q.xlsform_type
        row["name"] = q.name
        row["label"] = q.label or q.raw_label
        row["hint"] = q.hint
        row["required"] = "yes" if q.required else ""
        row["relevant"] = q.relevant
        row["constraint"] = q.constraint
        row["constraint_message"] = q.constraint_message
        row["calculation"] = q.calculation
        row["appearance"] = q.appearance
        row["default"] = q.default
        # calculate fields are never 'required'.
        if q.is_calculate:
            row["required"] = ""
        return row

    def _group_row(self, marker: str, group_name: str,
                   label: str = "") -> Dict[str, str]:
        row = {col: "" for col in SURVEY_COLUMNS}
        row["type"] = marker
        row["name"] = group_name
        if marker == "begin group":
            row["label"] = label
        return row

    @staticmethod
    def _unique_group_name(section: str, used: set) -> str:
        base = _NON_WORD.sub("_", section.lower()).strip("_")[:40] or "section"
        name = f"grp_{base}"
        counter = 2
        while name in used:
            name = f"grp_{base}_{counter}"
            counter += 1
        return name
