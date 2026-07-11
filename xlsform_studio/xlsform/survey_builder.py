"""Survey sheet builder (part of Module 4).

Purpose
-------
Turn the enriched questions of a :class:`Questionnaire` into rows for the
XLSForm ``survey`` sheet:

* sections become ``begin group``/``end group`` blocks — or ``begin repeat``/
  ``end repeat`` when the section is marked as repeating (a roster such as
  "for each household member");
* explicit structural rows (from JSON input or an imported XLSForm) pass
  through unchanged, in which case automatic section wrapping is disabled so
  the author's structure is authoritative;
* passthrough columns (translations like ``label::French (fr)``, media
  columns) are carried into the rows, and the union of their headers is
  reported via :meth:`extra_columns` so the exporter can emit them.

Inputs
------
A compiled :class:`~xlsform_studio.models.Questionnaire`.

Outputs
-------
A list of ``dict`` rows keyed by the survey columns defined in
:data:`xlsform_studio.app.config.SURVEY_COLUMNS` plus any extra columns.

Example
-------
>>> from xlsform_studio.models import Questionnaire, Question
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

_MARKERS = {"group": ("begin group", "end group"),
            "repeat": ("begin repeat", "end repeat")}


class SurveyBuilder:
    """Build the survey sheet rows."""

    def build(self, questionnaire: Questionnaire) -> List[Dict[str, str]]:
        # When the author supplied explicit structure, respect it verbatim.
        if any(q.is_structural for q in questionnaire.questions):
            return [self._structural_row(q) if q.is_structural
                    else self._question_row(q)
                    for q in questionnaire.questions]

        rows: List[Dict[str, str]] = []
        current_section = None
        current_group = ""
        current_kind = "group"
        used_groups: set = set()

        for q in questionnaire.questions:
            section = (q.section or "").strip()
            if section != current_section:
                if current_section:
                    rows.append(self._group_row(_MARKERS[current_kind][1],
                                                current_group))
                if section:
                    current_kind = "repeat" if q.section_type == "repeat" else "group"
                    current_group = self._unique_group_name(
                        section, used_groups, current_kind)
                    used_groups.add(current_group)
                    rows.append(self._group_row(_MARKERS[current_kind][0],
                                                current_group, section))
                current_section = section
            rows.append(self._question_row(q))

        if current_section:
            rows.append(self._group_row(_MARKERS[current_kind][1], current_group))
        return rows

    # ------------------------------------------------------------------
    def extra_columns(self, questionnaire: Questionnaire) -> List[str]:
        """Union of passthrough column headers, in first-seen order."""
        seen: List[str] = []
        for q in questionnaire.questions:
            for key in q.extra:
                if key not in seen and key not in SURVEY_COLUMNS:
                    seen.append(key)
        return seen

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
        row["choice_filter"] = q.choice_filter
        row["appearance"] = q.appearance
        row["default"] = q.default
        row.update(q.extra)
        # calculate fields are never 'required'.
        if q.is_calculate:
            row["required"] = ""
        return row

    def _structural_row(self, q: Question) -> Dict[str, str]:
        row = {col: "" for col in SURVEY_COLUMNS}
        row["type"] = q.base_type
        row["name"] = q.name
        if q.base_type.startswith("begin"):
            row["label"] = q.label or q.raw_label
            row["relevant"] = q.relevant
        row.update(q.extra)
        return row

    def _group_row(self, marker: str, group_name: str,
                   label: str = "") -> Dict[str, str]:
        row = {col: "" for col in SURVEY_COLUMNS}
        row["type"] = marker
        row["name"] = group_name
        if marker.startswith("begin"):
            row["label"] = label
        return row

    @staticmethod
    def _unique_group_name(section: str, used: set, kind: str = "group") -> str:
        prefix = "rpt" if kind == "repeat" else "grp"
        base = _NON_WORD.sub("_", section.lower()).strip("_")[:40] or "section"
        name = f"{prefix}_{base}"
        counter = 2
        while name in used:
            name = f"{prefix}_{base}_{counter}"
            counter += 1
        return name
