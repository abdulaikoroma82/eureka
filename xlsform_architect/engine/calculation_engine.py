"""Calculation engine (Module 7).

Purpose
-------
Emit XLSForm ``calculate`` fields for derived values commonly needed in
nutrition / M&E surveys:

* age in months / years from a date of birth
* BMI from weight & height
* MUAC nutritional classification (SAM / MAM / Normal)
* IMAM admission category from MUAC + oedema

Inputs
------
* A :class:`~xlsform_architect.models.Questionnaire` (to discover source
  variable names such as ``dob``, ``weight``, ``height``, ``muac``).
* The :class:`KnowledgeBase` for thresholds & expressions.

Outputs
-------
New calculate :class:`~xlsform_architect.models.Question` objects that can be
appended to the questionnaire.  Each carries an assumption note describing the
formula so it appears in the assumption log.

Example
-------
>>> from xlsform_architect.models import Questionnaire, Question
>>> qn = Questionnaire(questions=[Question(name="muac", xlsform_type="decimal",
...                                         raw_label="MUAC (cm)")])
>>> calcs = CalculationEngine().build(qn)
>>> any(c.name == "muac_class" for c in calcs)
True
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ..models import Question, Questionnaire
from .knowledge_base import KnowledgeBase


class CalculationEngine:
    """Generate calculate fields from known source variables."""

    def __init__(self, knowledge: Optional[KnowledgeBase] = None) -> None:
        self.kb = knowledge or KnowledgeBase.load()
        self.nutrition = self.kb.nutrition_rules
        self.imam = self.kb.imam_rules

    # ------------------------------------------------------------------
    def build(self, questionnaire: Questionnaire) -> List[Question]:
        """Return calculate questions derivable from *questionnaire*."""
        names = self._index(questionnaire)
        calcs: List[Question] = []
        existing = {q.name for q in questionnaire.questions}

        dob = names.get("dob") or names.get("birth") or names.get("date_of_birth")
        weight = names.get("weight")
        height = names.get("height") or names.get("length")
        muac = names.get("muac")
        oedema = names.get("oedema")

        if dob and "age_months" not in existing:
            expr = (self.nutrition.get("age", {})
                    .get("months_from_dob_expression", "int((today() - ${dob}) div 30.4375)"))
            calcs.append(self._calc(
                "age_months", "Age in months (calculated)",
                expr.replace("${dob}", f"${{{dob}}}"),
                "Age in months derived from date of birth."))

        if weight and height and "bmi" not in existing:
            expr = (self.nutrition.get("bmi", {})
                    .get("expression",
                         "${weight} div ((${height} div 100) * (${height} div 100))"))
            expr = expr.replace("${weight}", f"${{{weight}}}").replace("${height}", f"${{{height}}}")
            calcs.append(self._calc("bmi", "Body Mass Index (calculated)", expr,
                                    "BMI = weight(kg) / height(m)^2."))

        if muac and "muac_class" not in existing:
            expr = (self.nutrition.get("muac", {})
                    .get("classification_expression",
                         "if(${muac} < 11.5, 'sam', if(${muac} < 12.5, 'mam', 'normal'))"))
            expr = expr.replace("${muac}", f"${{{muac}}}").strip()
            calcs.append(self._calc("muac_class", "MUAC classification (calculated)", expr,
                                    "MUAC classification: <11.5=SAM, 11.5-12.4=MAM, >=12.5=Normal."))

        if muac and oedema and "imam_admission" not in existing:
            expr = self.imam.get("admission_category_expression", "")
            if expr:
                expr = expr.replace("${muac}", f"${{{muac}}}").replace("${oedema}", f"${{{oedema}}}").strip()
                calcs.append(self._calc("imam_admission", "IMAM admission category (calculated)",
                                        expr, "IMAM admission category from MUAC and oedema."))

        return calcs

    # ------------------------------------------------------------------
    def _index(self, questionnaire: Questionnaire) -> Dict[str, str]:
        """Map source keywords to actual variable names present in the form."""
        index: Dict[str, str] = {}
        keys = ["dob", "birth", "date_of_birth", "weight", "height", "length",
                "muac", "oedema", "edema"]
        for q in questionnaire.questions:
            hay = f"{q.name} {q.raw_label}".lower()
            for key in keys:
                if key.replace("_", " ") in hay or key in q.name.lower():
                    index.setdefault("oedema" if key == "edema" else key, q.name)
        return index

    @staticmethod
    def _calc(name: str, label: str, calculation: str, note: str) -> Question:
        # Collapse any folded-YAML newlines into a single-line expression.
        calculation = " ".join(calculation.split())
        q = Question(raw_label=label, name=name, xlsform_type="calculate",
                     label=label, calculation=calculation)
        q.add_assumption(note)
        return q
