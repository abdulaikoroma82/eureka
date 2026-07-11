"""Survey duration & respondent-burden estimator (deterministic; Module D8).

Purpose
-------
Estimate how long an interview takes and how heavy it feels, *before* the
form reaches the field. Pilot data is always better - but a deterministic
estimate from question structure catches the "this baseline takes two
hours" problem at design time, when it is cheap to fix.

Formulas (all tunable constants below, documented for auditability)
-------------------------------------------------------------------
Per-question base time by answer type (seconds), plus:

* select questions: reading time per visible option;
* open text: extra composition burden;
* repeats: the block's time multiplied by an assumed instance count;
* conditional questions: counted at 60% weight (typically only a subset
  of respondents sees them).

Cognitive load counts *decisions and recall effort* rather than seconds:
long option lists, open recall questions and repeat blocks weigh most.

Risk ratings follow common survey-methodology guidance: face-to-face
household interviews stay reliable up to ~30-40 minutes; past ~60 minutes
data quality measurably degrades.

Inputs
------
A compiled :class:`~xlsform_studio.models.Questionnaire`.

Outputs
-------
A :class:`DurationEstimate` (minutes low/typical/high, per-section
breakdown, cognitive-load score, burden risk rating).

Example
-------
>>> from xlsform_studio.models import Questionnaire, Question
>>> qn = Questionnaire(questions=[Question(name="age", label="Age?",
...                                        xlsform_type="integer")])
>>> DurationEstimator().estimate(qn).typical_minutes < 1
True
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from ..models import Question, Questionnaire

#: Base answer time per question type, in seconds (median enumerator-led
#: interview pace; self-administered forms trend slower on open text).
_BASE_SECONDS: Dict[str, float] = {
    "note": 6, "integer": 12, "decimal": 14, "text": 25, "date": 12,
    "time": 10, "datetime": 14, "select_one": 10, "select_multiple": 14,
    "rank": 25, "geopoint": 30, "image": 35, "audio": 30, "video": 45,
    "file": 30, "barcode": 15, "calculate": 0,
}
_DEFAULT_SECONDS = 15.0
#: Reading/considering time per visible choice option.
_PER_OPTION_SECONDS = 1.5
#: Assumed instances when a repeat has no declared count.
_ASSUMED_REPEAT_COUNT = 4
#: Weight applied to conditional questions (only some respondents see them).
_RELEVANT_WEIGHT = 0.6
#: Uncertainty band around the typical estimate.
_LOW_FACTOR, _HIGH_FACTOR = 0.7, 1.5

#: Cognitive-load points (decisions / recall effort, not seconds).
_LOAD_OPEN_TEXT = 3.0
_LOAD_LONG_LIST = 2.0         # select with more than 7 options
_LOAD_SELECT_MULTIPLE = 1.5
_LOAD_REPEAT_BLOCK = 4.0
_LOAD_DEFAULT = 1.0

#: Interview-length risk thresholds (minutes, typical estimate).
_RISK_BANDS = ((20, "low"), (40, "moderate"), (60, "high"))


@dataclass
class DurationEstimate:
    """Deterministic interview-length and burden estimate."""

    low_minutes: float
    typical_minutes: float
    high_minutes: float
    question_count: int
    cognitive_load: float               # total load points
    burden_risk: str                    # low | moderate | high | severe
    per_section_minutes: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "low_minutes": round(self.low_minutes, 1),
            "typical_minutes": round(self.typical_minutes, 1),
            "high_minutes": round(self.high_minutes, 1),
            "question_count": self.question_count,
            "cognitive_load": round(self.cognitive_load, 1),
            "burden_risk": self.burden_risk,
            "per_section_minutes": {k: round(v, 1)
                                    for k, v in self.per_section_minutes.items()},
            "notes": self.notes,
        }


class DurationEstimator:
    """Estimate interview duration from form structure alone."""

    def estimate(self, questionnaire: Questionnaire) -> DurationEstimate:
        total_seconds = 0.0
        load = 0.0
        per_section: Dict[str, float] = {}
        notes: List[str] = []
        question_count = 0
        repeat_depth = 0

        for q in questionnaire.questions:
            if q.base_type == "begin repeat":
                repeat_depth += 1
                load += _LOAD_REPEAT_BLOCK
                continue
            if q.base_type == "end repeat":
                repeat_depth = max(0, repeat_depth - 1)
                continue
            if q.is_structural:
                continue

            seconds = self._question_seconds(q, questionnaire)
            if q.relevant:
                seconds *= _RELEVANT_WEIGHT
            if repeat_depth:
                seconds *= _ASSUMED_REPEAT_COUNT ** repeat_depth
            total_seconds += seconds
            if not q.is_calculate:
                question_count += 1
                load += self._question_load(q, questionnaire)
            section = q.section or "(no section)"
            per_section[section] = per_section.get(section, 0.0) + seconds

        typical = total_seconds / 60.0
        risk = "severe"
        for limit, rating in _RISK_BANDS:
            if typical <= limit:
                risk = rating
                break

        if risk in ("high", "severe"):
            notes.append(f"A typical interview of ~{typical:.0f} minutes "
                         f"risks respondent fatigue; consider splitting the "
                         f"form or trimming sections.")
        longest = max(per_section.items(), key=lambda kv: kv[1], default=None)
        if longest and typical > 0 and longest[1] / 60.0 > typical * 0.4:
            notes.append(f"Section '{longest[0]}' alone accounts for "
                         f"{longest[1] / 60.0:.0f} of ~{typical:.0f} "
                         f"minutes - the heaviest part of the interview.")

        return DurationEstimate(
            low_minutes=typical * _LOW_FACTOR,
            typical_minutes=typical,
            high_minutes=typical * _HIGH_FACTOR,
            question_count=question_count,
            cognitive_load=load,
            burden_risk=risk,
            per_section_minutes={k: v / 60.0 for k, v in per_section.items()},
            notes=notes)

    # ------------------------------------------------------------------
    def _question_seconds(self, q: Question, qn: Questionnaire) -> float:
        seconds = _BASE_SECONDS.get(q.base_type, _DEFAULT_SECONDS)
        if q.references_choices:
            seconds += self._option_count(q, qn) * _PER_OPTION_SECONDS
        return seconds

    def _question_load(self, q: Question, qn: Questionnaire) -> float:
        if q.base_type == "text":
            return _LOAD_OPEN_TEXT
        if q.references_choices:
            load = (_LOAD_SELECT_MULTIPLE
                    if q.base_type == "select_multiple" else _LOAD_DEFAULT)
            if self._option_count(q, qn) > 7:
                load += _LOAD_LONG_LIST
            return load
        return _LOAD_DEFAULT

    @staticmethod
    def _option_count(q: Question, qn: Questionnaire) -> int:
        parts = (q.xlsform_type or "").split()
        list_name = parts[1] if len(parts) >= 2 else q.list_name
        cl = qn.choice_lists.get(list_name)
        return len(cl.choices) if cl else 0
