"""Calculation engine (Module 7).

Purpose
-------
Emit XLSForm ``calculate`` fields for standard derived values.  The bundled
behaviour is domain-neutral: it generates an **age** field from a date of
birth, which is one of the most common XLSForm idioms and applies to almost
any questionnaire.

Additional derived calculations can be added declaratively in
``knowledge/xlsform_rules.yaml`` under ``calculations`` without changing this
code.

Inputs
------
* A :class:`~xlsform_studio.models.Questionnaire` (to discover the source
  date-of-birth variable).
* The :class:`KnowledgeBase` for the standard expressions.

Outputs
-------
New calculate :class:`~xlsform_studio.models.Question` objects that can be
appended to the questionnaire.  Each carries an assumption note describing the
formula so it appears in the assumption log.

Example
-------
>>> from xlsform_studio.models import Questionnaire, Question
>>> qn = Questionnaire(questions=[Question(name="dob", xlsform_type="date",
...                                         raw_label="Date of birth")])
>>> calcs = CalculationEngine().build(qn)
>>> any(c.name == "age_years" for c in calcs)
True
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ..models import Question, Questionnaire
from .knowledge_base import KnowledgeBase


class CalculationEngine:
    """Generate standard calculate fields from known source variables."""

    def __init__(self, knowledge: Optional[KnowledgeBase] = None) -> None:
        self.kb = knowledge or KnowledgeBase.load()
        self.calc_exprs = self.kb.calculations()

    # ------------------------------------------------------------------
    def build(self, questionnaire: Questionnaire) -> List[Question]:
        """Return calculate questions derivable from *questionnaire*."""
        names = self._index(questionnaire)
        calcs: List[Question] = []
        existing = {q.name for q in questionnaire.questions}

        dob = names.get("dob") or names.get("date_of_birth") or names.get("birth")

        if dob and "age_years" not in existing:
            expr = self.calc_exprs.get("age_years_from_dob",
                                       "int((today() - ${dob}) div 365.25)")
            calc = self._calc(
                "age_years", "Age in years (calculated)",
                expr.replace("${dob}", f"${{{dob}}}"),
                "Age in years derived from date of birth.")
            # Live in the same section (and repeat, if any) as the source:
            # a calculation outside a repeat cannot see variables inside it.
            source = next((q for q in questionnaire.questions
                           if q.name == dob), None)
            if source is not None:
                calc.section = source.section
                calc.section_type = source.section_type
            calcs.append(calc)

        return calcs

    # ------------------------------------------------------------------
    def _index(self, questionnaire: Questionnaire) -> Dict[str, str]:
        """Map source keywords to actual variable names present in the form."""
        index: Dict[str, str] = {}
        keys = ["date of birth", "date_of_birth", "dob", "birth"]
        for q in questionnaire.questions:
            hay = f"{q.name} {q.raw_label}".lower()
            for key in keys:
                if key in hay or key.replace(" ", "_") in q.name.lower():
                    canonical = "dob" if key in ("dob", "birth") else "date_of_birth"
                    index.setdefault(canonical, q.name)
        return index

    @staticmethod
    def _calc(name: str, label: str, calculation: str, note: str) -> Question:
        # Collapse any folded-YAML newlines into a single-line expression.
        calculation = " ".join(calculation.split())
        q = Question(raw_label=label, name=name, xlsform_type="calculate",
                     label=label, calculation=calculation)
        q.add_assumption(note)
        return q
