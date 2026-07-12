"""Deterministic form analysis (quality scoring, duration, diffing).

Everything in this package is derived arithmetically from the compiled
:class:`~xlsform_studio.models.Questionnaire` - no network, no models,
same input always the same output.
"""

from .diff import QuestionnaireDiff
from .duration import DurationEstimate, DurationEstimator
from .quality_score import QualityIndex, QualityScorer

__all__ = ["DurationEstimate", "DurationEstimator", "QualityIndex",
          "QualityScorer", "QuestionnaireDiff"]
