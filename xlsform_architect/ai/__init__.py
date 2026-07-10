"""Optional AI-assisted layer (DeepSeek).

This package is the ONLY part of XLSForm Architect that makes network
calls. It is entirely opt-in: every feature here requires an explicit
:class:`~xlsform_architect.ai.config.AIConfig` with ``enabled=True`` AND a
configured ``DEEPSEEK_API_KEY``. With neither present, the deterministic
pipeline in the rest of the package behaves exactly as it did before this
package existed - zero cost, zero network activity, zero new dependency.

See :class:`~xlsform_architect.ai.pipeline.AIPipeline` for the integration
point, and the individual feature modules for what each one does:

* :mod:`translator` - generate translation columns
* :mod:`skip_logic` - resolve "skip to question N" jumps and other
  unparseable conditional logic
* :mod:`constraint_reviewer` - suggest cross-field validation constraints
  (e.g. end date after start date) that a single-question constraint engine
  cannot express
* :mod:`type_classifier` - reclassify keyword-fallback "text" questions
* :mod:`quality_reviewer` - holistic semantic review of the compiled form
"""

from .client import AIError, DeepSeekClient, get_default_client
from .config import AIConfig
from .pipeline import AIPipeline

__all__ = ["AIConfig", "AIError", "AIPipeline", "DeepSeekClient",
          "get_default_client"]
