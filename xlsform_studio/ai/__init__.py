"""AI layer (DeepSeek).

This package is the ONLY part of XLSForm Studio that makes network calls.
It is home to two things:

* :mod:`form_author` - the essential AI author that drafts every field of
  the form (type, name, label, hint, relevance, constraints, calculations,
  choices). A run cannot produce a form without it, so a configured
  ``DEEPSEEK_API_KEY`` is required.
* the optional *enrichment* passes below, which refine or review that
  authored draft and stay off unless explicitly enabled in
  :class:`~xlsform_studio.ai.config.AIConfig`.

See :class:`~xlsform_studio.ai.pipeline.AIPipeline` for the enrichment
integration point, and the individual feature modules for what each does:

* :mod:`translator` - generate translation columns (only fills gaps; never
  overwrites a translation you already supplied)
* :mod:`constraint_reviewer` - suggest cross-field validation constraints
  (e.g. end date after start date) that span two questions
* :mod:`quality_reviewer` - holistic review of the authored form: semantic
  contradictions, advisory naming/label clarity commentary, and
  respondent-experience checks (ambiguous phrasing, contradictory option
  lists, redundant questions, incoherent skip chains)
* :mod:`finding_explainer` - adds a plain-English explanation to the
  deterministic validator's own findings, after validation runs
"""

from .client import AIError, DeepSeekClient, get_default_client
from .config import AIConfig
from .pipeline import AIPipeline

__all__ = ["AIConfig", "AIError", "AIPipeline", "DeepSeekClient",
          "get_default_client"]
