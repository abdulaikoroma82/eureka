"""Deterministic form analysis (quality scoring, duration, diffing).

Everything in this package is derived arithmetically from the compiled
:class:`~xlsform_architect.models.Questionnaire` - no network, no models,
same input always the same output. The optional AI layer may *narrate*
these numbers (see :mod:`xlsform_architect.ai.narrative`), but it never
computes them.
"""

from .diff import QuestionnaireDiff
from .duration import DurationEstimate, DurationEstimator
from .quality_score import QualityIndex, QualityScorer

__all__ = ["DurationEstimate", "DurationEstimator", "QualityIndex",
          "QualityScorer", "QuestionnaireDiff"]
