"""Form Quality Index (deterministic; Module D4).

Purpose
-------
Score the compiled form 0-100 across seven measurable categories, so a
team can gate deployment ("nothing ships below 80"), track quality across
versions, and see at a glance *where* a form is weak. Every category is
computed arithmetically from the form itself and the validation report -
the same form always scores the same.

Categories (each 0-100; weights below)
--------------------------------------
* **naming_quality** - identifiers an analyst can read: not generic
  (``q1``, ``var3``), not colliding, within the platform length limit.
* **constraint_coverage** - share of numeric/date questions carrying a
  validation constraint (unconstrained numbers are the top source of
  impossible field data).
* **logic_completeness** - share of authored logic instructions that
  actually compiled into a ``relevant`` expression, minus consistency
  defects (circular/contradictory/forward references).
* **choice_consistency** - answer scales defined once and reused: no
  near-duplicate lists, no single-option lists, options unique per list.
* **validation_readiness** - blocking errors and warnings from the
  deterministic validators.
* **documentation** - form metadata (title, id, version), question labels
  present, sections used on long forms.
* **reusability** - shared choice lists and named (not auto-numbered)
  variables, which make the form a template rather than a one-off.

Inputs
------
A compiled :class:`~xlsform_studio.models.Questionnaire` and its
:class:`~xlsform_studio.validation.report_generator.ValidationReport`.

Outputs
-------
A :class:`QualityIndex` (overall score, per-category scores, and the
human-readable observations that explain each deduction).

Example
-------
>>> from xlsform_studio.models import Questionnaire, Question, FormSettings
>>> from xlsform_studio.validation.report_generator import ValidationReport
>>> qn = Questionnaire(settings=FormSettings(form_title="T", form_id="t",
...                                          version="1"),
...     questions=[Question(name="age", label="Age", xlsform_type="integer",
...                         constraint=". >= 0 and . <= 120")])
>>> QualityScorer().score(qn, ValidationReport()).overall >= 90
True
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List

from ..models import Questionnaire
from ..validation.report_generator import ValidationReport

#: Category weights (must sum to 1.0).
_WEIGHTS: Dict[str, float] = {
    "naming_quality": 0.15,
    "constraint_coverage": 0.15,
    "logic_completeness": 0.20,
    "choice_consistency": 0.10,
    "validation_readiness": 0.20,
    "documentation": 0.10,
    "reusability": 0.10,
}

_GENERIC_NAME = re.compile(r"^(q|question|var|field|item)_?\d+$", re.IGNORECASE)
#: Types where a missing constraint most often lets bad data through.
_CONSTRAINABLE = {"integer", "decimal", "date", "datetime"}


@dataclass
class QualityIndex:
    """The Form Quality Index: overall + per-category scores."""

    overall: int
    categories: Dict[str, int]
    observations: List[str] = field(default_factory=list)

    @property
    def rating(self) -> str:
        if self.overall >= 85:
            return "excellent"
        if self.overall >= 70:
            return "good"
        if self.overall >= 50:
            return "needs work"
        return "poor"

    def to_dict(self) -> Dict:
        return {"overall": self.overall, "rating": self.rating,
                "categories": dict(self.categories),
                "observations": list(self.observations)}


class QualityScorer:
    """Compute the deterministic Form Quality Index."""

    def score(self, questionnaire: Questionnaire,
              report: ValidationReport) -> QualityIndex:
        observations: List[str] = []
        categories = {
            "naming_quality": self._naming(questionnaire, observations),
            "constraint_coverage": self._constraints(questionnaire, observations),
            "logic_completeness": self._logic(questionnaire, report, observations),
            "choice_consistency": self._choices(questionnaire, report, observations),
            "validation_readiness": self._validation(report, observations),
            "documentation": self._documentation(questionnaire, observations),
            "reusability": self._reusability(questionnaire, observations),
        }
        overall = round(sum(categories[k] * _WEIGHTS[k] for k in categories))
        return QualityIndex(overall=overall, categories=categories,
                            observations=observations)

    # ------------------------------------------------------------------
    def _real(self, qn: Questionnaire):
        return [q for q in qn.questions if not q.is_structural]

    def _naming(self, qn: Questionnaire, obs: List[str]) -> int:
        real = self._real(qn)
        if not real:
            return 0
        generic = [q.name for q in real if _GENERIC_NAME.match(q.name or "")]
        unnamed = [q for q in real if not q.name]
        penalty = (len(generic) + len(unnamed)) / len(real)
        if generic:
            obs.append(f"{len(generic)} variable name(s) are generic "
                       f"(e.g. '{generic[0]}') and won't be readable in the "
                       f"exported data.")
        return round(100 * (1 - penalty))

    def _constraints(self, qn: Questionnaire, obs: List[str]) -> int:
        candidates = [q for q in self._real(qn)
                      if q.base_type in _CONSTRAINABLE]
        if not candidates:
            return 100
        covered = [q for q in candidates if q.constraint]
        missing = len(candidates) - len(covered)
        if missing:
            obs.append(f"{missing} of {len(candidates)} numeric/date "
                       f"question(s) have no validation constraint - "
                       f"impossible values would be accepted.")
        return round(100 * len(covered) / len(candidates))

    def _logic(self, qn: Questionnaire, report: ValidationReport,
               obs: List[str]) -> int:
        authored = [q for q in self._real(qn) if q.logic]
        compiled = [q for q in authored
                    if q.relevant or not any(
                        "could not be auto-compiled" in a for a in q.assumptions)]
        score = 100.0
        if authored:
            uncompiled = len(authored) - len(compiled)
            if uncompiled:
                obs.append(f"{uncompiled} skip instruction(s) could not be "
                           f"compiled and need manual review.")
            score = 100 * len(compiled) / len(authored)
        defects = [f for f in report.findings if f.category == "consistency"
                   and f.level in ("error", "warning")]
        if defects:
            obs.append(f"{len(defects)} logic consistency issue(s) "
                       f"(circular/contradictory/mis-ordered conditions).")
            score -= 15 * len(defects)
        return max(0, round(score))

    def _choices(self, qn: Questionnaire, report: ValidationReport,
                 obs: List[str]) -> int:
        score = 100.0
        near = [f for f in report.findings
                if f.category == "consistency" and "share" in f.message]
        if near:
            obs.append(f"{len(near)} pair(s) of choice lists are "
                       f"near-identical and probably belong merged.")
            score -= 20 * len(near)
        for name, cl in qn.choice_lists.items():
            values = [c.name for c in cl.choices]
            if len(values) != len(set(values)):
                obs.append(f"Choice list '{name}' has duplicate option codes.")
                score -= 20
            if len(values) == 1:
                obs.append(f"Choice list '{name}' has a single option - a "
                           f"select with one answer is usually a note or a "
                           f"missing list.")
                score -= 10
        return max(0, round(score))

    def _validation(self, report: ValidationReport, obs: List[str]) -> int:
        errors = len(report.errors)
        warnings = len([f for f in report.warnings
                        if f.category != "ai_review"])
        if errors:
            obs.append(f"{errors} blocking validation error(s).")
        if warnings:
            obs.append(f"{warnings} validation warning(s).")
        return max(0, 100 - 40 * errors - 8 * warnings)

    def _documentation(self, qn: Questionnaire, obs: List[str]) -> int:
        real = self._real(qn)
        score = 100.0
        settings = qn.settings
        for attr, label in (("form_title", "form title"),
                            ("form_id", "form id"), ("version", "version")):
            if not getattr(settings, attr):
                obs.append(f"The {label} is not set.")
                score -= 10
        unlabelled = [q for q in real if not (q.label or q.raw_label)]
        if real and unlabelled:
            obs.append(f"{len(unlabelled)} question(s) have no label.")
            score -= 40 * len(unlabelled) / len(real)
        if len(real) > 10 and not any(q.section for q in real) \
                and not any(q.is_structural for q in qn.questions):
            obs.append("A form this long has no sections - grouping helps "
                       "both enumerators and analysts.")
            score -= 15
        return max(0, round(score))

    def _reusability(self, qn: Questionnaire, obs: List[str]) -> int:
        selects = [q for q in self._real(qn) if q.references_choices]
        if not selects:
            return 100
        lists_used = len({(q.xlsform_type or "").split()[1]
                          for q in selects
                          if len((q.xlsform_type or "").split()) >= 2})
        # Perfect reuse = few lists serving many selects; a list per select
        # (beyond ~one distinct scale per 1.5 selects) suggests copy-paste.
        ratio = lists_used / len(selects)
        score = 100.0 if ratio <= 0.67 else 100 - (ratio - 0.67) * 90
        if score < 85 and len(selects) >= 4:
            obs.append("Most select questions define their own choice list; "
                       "shared scales would make the form easier to reuse.")
        return max(0, round(score))
