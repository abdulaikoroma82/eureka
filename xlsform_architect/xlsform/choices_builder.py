"""Choices sheet builder (part of Module 4).

Purpose
-------
Emit rows for the XLSForm ``choices`` sheet from the questionnaire's choice
lists.  Only lists that are actually referenced by a survey question are
exported, keeping the sheet clean.

Inputs
------
A compiled :class:`~xlsform_architect.models.Questionnaire`.

Outputs
-------
A list of ``{"list_name","name","label"}`` dict rows.

Example
-------
>>> from xlsform_architect.models import Questionnaire, ChoiceList, Choice, Question
>>> qn = Questionnaire(
...     questions=[Question(name="q", xlsform_type="select_one sex", list_name="sex")],
...     choice_lists={"sex": ChoiceList("sex", [Choice("1", "Male"), Choice("2", "Female")])})
>>> ChoicesBuilder().build(qn)[0]
{'list_name': 'sex', 'name': '1', 'label': 'Male'}
"""

from __future__ import annotations

from typing import Dict, List, Set

from ..app.config import CHOICES_COLUMNS
from ..models import Questionnaire


class ChoicesBuilder:
    """Build the choices sheet rows."""

    def build(self, questionnaire: Questionnaire) -> List[Dict[str, str]]:
        referenced = self._referenced_lists(questionnaire)
        rows: List[Dict[str, str]] = []

        # Preserve deterministic ordering: referenced lists in first-use order.
        for list_name in self._ordered_lists(questionnaire, referenced):
            cl = questionnaire.choice_lists.get(list_name)
            if not cl:
                continue
            for choice in cl.choices:
                row = {
                    "list_name": cl.list_name,
                    "name": choice.name,
                    "label": choice.label,
                }
                row.update(choice.extra)
                rows.append(row)
        return rows

    # ------------------------------------------------------------------
    def extra_columns(self, questionnaire: Questionnaire) -> List[str]:
        """Union of passthrough choice column headers, in first-seen order."""
        seen: List[str] = []
        for cl in questionnaire.choice_lists.values():
            for choice in cl.choices:
                for key in choice.extra:
                    if key not in seen and key not in CHOICES_COLUMNS:
                        seen.append(key)
        return seen

    # ------------------------------------------------------------------
    @staticmethod
    def _referenced_lists(questionnaire: Questionnaire) -> Set[str]:
        refs: Set[str] = set()
        for q in questionnaire.questions:
            if q.references_choices:
                parts = q.xlsform_type.split()
                if len(parts) >= 2:
                    refs.add(parts[1])
                if q.list_name:
                    refs.add(q.list_name)
        return refs

    @staticmethod
    def _ordered_lists(questionnaire: Questionnaire, referenced: Set[str]) -> List[str]:
        ordered: List[str] = []
        for q in questionnaire.questions:
            if not q.references_choices:
                continue
            parts = q.xlsform_type.split()
            name = parts[1] if len(parts) >= 2 else q.list_name
            if name and name in referenced and name not in ordered:
                ordered.append(name)
        # Include any referenced lists not yet ordered (defensive).
        for name in referenced:
            if name not in ordered:
                ordered.append(name)
        return ordered
