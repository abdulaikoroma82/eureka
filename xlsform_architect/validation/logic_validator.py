"""Logic validator (part of Module 9).

Purpose
-------
Catch logical defects that break XLSForms at deployment time:

* duplicate variable names
* ``${...}`` references to variables that do not exist
* select questions whose choice list is missing or empty
* choice lists containing duplicate choice names

Inputs
------
A compiled :class:`~xlsform_architect.models.Questionnaire`.

Outputs
-------
A list of :class:`~xlsform_architect.validation.report_generator.Finding`.

Example
-------
>>> from xlsform_architect.models import Questionnaire, Question
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

        return findings
