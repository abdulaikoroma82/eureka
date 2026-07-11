"""Logic validator.

Purpose
-------
Catch logical defects that break XLSForms at deployment time:

* duplicate variable names
* ``${...}`` references to variables that do not exist
* select questions whose choice list is missing or empty
* choice lists containing duplicate choice names

Inputs
------
A compiled :class:`~xlsform_studio.models.Questionnaire`.

Outputs
-------
A list of :class:`~xlsform_studio.validation.report_generator.Finding`.

Example
-------
>>> from xlsform_studio.models import Questionnaire, Question
>>> qn = Questionnaire(questions=[
...     Question(name="a", xlsform_type="integer", label="A"),
...     Question(name="b", xlsform_type="integer", label="B", relevant="${missing}>1")])
>>> [f.message for f in LogicValidator().validate(qn) if f.level == "error"]
["Question 'b' references unknown variable '${missing}'."]
"""

from __future__ import annotations

import re
from typing import List, Set

from ..models import Questionnaire
from .report_generator import Finding

_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class LogicValidator:
    """Reference and uniqueness checks."""

    def validate(self, questionnaire: Questionnaire) -> List[Finding]:
        findings: List[Finding] = []
        questions = [q for q in questionnaire.questions
                    if not q.is_structural]

        names = [q.name for q in questions if q.name]
        name_set: Set[str] = set(names)

        # --- duplicate names -------------------------------------------
        seen: Set[str] = set()
        for n in names:
            if n in seen:
                findings.append(Finding("error", "logic",
                                        f"Duplicate variable name '{n}'.", n))
            seen.add(n)

        # --- broken references -----------------------------------------
        for q in questions:
            for expr in (q.relevant, q.constraint, q.calculation):
                for ref in _REF.findall(expr or ""):
                    if ref not in name_set:
                        findings.append(Finding(
                            "error", "logic",
                            f"Question '{q.name}' references unknown variable '${{{ref}}}'.",
                            q.name))

        # --- missing / empty choice lists ------------------------------
        for q in questions:
            if not q.references_choices:
                continue
            parts = q.xlsform_type.split()
            list_name = parts[1] if len(parts) >= 2 else ""
            cl = questionnaire.choice_lists.get(list_name)
            if cl is None:
                findings.append(Finding("error", "logic",
                                        f"Select question '{q.name}' uses undefined list '{list_name}'.",
                                        q.name))
            elif not cl.choices:
                findings.append(Finding("error", "logic",
                                        f"Choice list '{list_name}' (used by '{q.name}') is empty.",
                                        q.name))

        # --- duplicate choice names within a list ----------------------
        for list_name, cl in questionnaire.choice_lists.items():
            seen_c: Set[str] = set()
            for ch in cl.choices:
                if ch.name in seen_c:
                    findings.append(Finding("warning", "logic",
                                            f"Choice list '{list_name}' has duplicate name '{ch.name}'.",
                                            list_name))
                seen_c.add(ch.name)

        # --- compared choice values actually exist ----------------------
        findings.extend(self._check_choice_values(questionnaire, questions))

        return findings

    # ------------------------------------------------------------------
    #: ${field}='value' comparisons and selected(${field}, 'value') calls.
    _EQ_VALUE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}\s*(?:!=|=)\s*'([^']*)'")
    _SELECTED_VALUE = re.compile(
        r"selected\(\s*\$\{([A-Za-z_][A-Za-z0-9_]*)\}\s*,\s*'([^']*)'\s*\)")

    def _check_choice_values(self, questionnaire: Questionnaire,
                             questions: list) -> List[Finding]:
        """Flag comparisons against values a select question can never hold.

        Catches the silent skip-logic killer: ``${sex}='malee'`` (typo) or
        ``${enrolled}='yes'`` when the list stores 1/0. The condition is
        syntactically valid and deploys fine - it just never fires.
        """
        findings: List[Finding] = []

        # Map each select/rank question to its choice-name set.
        value_sets = {}
        for q in questions:
            if not q.references_choices:
                continue
            parts = q.xlsform_type.split()
            list_name = parts[1] if len(parts) >= 2 else q.list_name
            cl = questionnaire.choice_lists.get(list_name)
            if cl and cl.choices:
                value_sets[q.name] = {c.name for c in cl.choices}

        seen: Set[tuple] = set()
        for q in questions:
            for expr in (q.relevant, q.constraint, q.calculation,
                         getattr(q, "choice_filter", "")):
                if not expr:
                    continue
                matches = (self._EQ_VALUE.findall(expr)
                          + self._SELECTED_VALUE.findall(expr))
                for field, value in matches:
                    if field not in value_sets or not value:
                        continue
                    if value in value_sets[field]:
                        continue
                    key = (q.name, field, value)
                    if key in seen:
                        continue
                    seen.add(key)
                    options = ", ".join(sorted(value_sets[field])[:8])
                    findings.append(Finding(
                        "warning", "logic",
                        f"'{q.name}' compares ${{{field}}} to '{value}', but "
                        f"that list's stored values are: {options}. The "
                        f"condition can never be true as written.", q.name))
        return findings
