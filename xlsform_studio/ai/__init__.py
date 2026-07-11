"""Optional AI-assisted layer (DeepSeek).

This package is the ONLY part of XLSForm Studio that makes network
calls. It is entirely opt-in: every feature here requires an explicit
:class:`~xlsform_studio.ai.config.AIConfig` with ``enabled=True`` AND a
configured ``DEEPSEEK_API_KEY``. With neither present, the deterministic
pipeline in the rest of the package behaves exactly as it did before this
package existed - zero cost, zero network activity, zero new dependency.

See :class:`~xlsform_studio.ai.pipeline.AIPipeline` for the integration
point, and the individual feature modules for what each one does:

* :mod:`translator` - generate translation columns (only fills gaps; never
  overwrites a translation you already supplied - a genuine rules/AI
  co-share on the same output)
* :mod:`skip_logic` - resolve "skip to question N" jumps and other
  unparseable conditional logic
* :mod:`domain_constraints` - propose domain-aware single-field bounds
  (grounded in an optional survey-context description) for questions the
  deterministic constraint engine left unconstrained; never touches a
  question that already has a constraint
* :mod:`constraint_reviewer` - suggest cross-field validation constraints
  (e.g. end date after start date) that a single-question constraint engine
  cannot express; combines with an existing single-field constraint rather
  than discarding it - another rules/AI co-share
* :mod:`type_classifier` - reclassify keyword-fallback "text" questions
* :mod:`quality_reviewer` - holistic review of the compiled form: semantic
  contradictions, advisory-only naming/label clarity commentary (never
  renames anything - the rule engine keeps sole ownership of names), and
  respondent-experience checks (ambiguous phrasing, contradictory option
  lists, redundant questions, incoherent skip chains)
* :mod:`finding_explainer` - adds a plain-English explanation to the
  deterministic validator's own findings, after validation runs; a strict
  co-share where rules own every fact and AI only makes them easier to read
"""

from .client import AIError, DeepSeekClient, get_default_client
from .config import AIConfig
from .pipeline import AIPipeline

__all__ = ["AIConfig", "AIError", "AIPipeline", "DeepSeekClient",
          "get_default_client"]
