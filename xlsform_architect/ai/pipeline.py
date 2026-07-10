"""AI pipeline orchestrator (optional AI layer).

Purpose
-------
Run the enabled AI-assisted features, in a fixed order, over an already
rule-engine-compiled questionnaire:

    1. Type-classification fallback (may change a question's type, so it
       runs first - everything downstream should see the corrected type)
    2. Skip-logic inversion (adds ``relevant`` conditions)
    3. Translation (labels are final by now, so translations are accurate)
    4. Quality review (reads the fully-settled form last)

This is the single integration point :class:`~xlsform_architect.app.
workflow.Workflow` calls; it is a no-op with zero network activity whenever
:class:`~xlsform_architect.ai.config.AIConfig` is disabled or no client is
available, so the deterministic pipeline's behaviour is completely
unaffected by this module's existence.

Inputs
------
A compiled :class:`~xlsform_architect.models.Questionnaire`, an
:class:`~xlsform_architect.ai.config.AIConfig`, and a
:class:`~xlsform_architect.ai.client.DeepSeekClient` (or ``None``).

Outputs
-------
The questionnaire (mutated in place where features applied changes), a list
of human-readable notes (folded into the assumption log), and a list of
:class:`~xlsform_architect.validation.report_generator.Finding` (folded into
the validation report).

Example
-------
>>> from xlsform_architect.ai.config import AIConfig
>>> qn, notes, findings = AIPipeline(client=None).run(Questionnaire(), AIConfig.disabled())
>>> notes
[]
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from ..models import Questionnaire
from ..validation.report_generator import Finding
from .client import DeepSeekClient
from .config import AIConfig
from .quality_reviewer import AIQualityReviewer
from .skip_logic import AISkipLogicResolver
from .translator import AITranslator
from .type_classifier import AITypeClassifier


class AIPipeline:
    """Run the enabled AI features over a compiled questionnaire."""

    def __init__(self, client: Optional[DeepSeekClient]) -> None:
        self.client = client

    # ------------------------------------------------------------------
    def run(self, questionnaire: Questionnaire,
            config: AIConfig) -> Tuple[Questionnaire, List[str], List[Finding]]:
        notes: List[str] = []
        findings: List[Finding] = []

        if not config.any_feature_enabled:
            return questionnaire, notes, findings

        if self.client is None or not self.client.available:
            notes.append("[AI] AI features were requested but no API key is "
                        "configured (DEEPSEEK_API_KEY); AI enrichment was "
                        "skipped and the deterministic result stands.")
            return questionnaire, notes, findings

        if config.wants("classify"):
            notes.extend(AITypeClassifier(self.client).classify(questionnaire))

        if config.wants("skip_logic"):
            notes.extend(AISkipLogicResolver(self.client).resolve(questionnaire))

        if config.wants("translate") and config.translate_languages:
            notes.extend(AITranslator(self.client).translate(
                questionnaire, config.translate_languages))

        if config.wants("review"):
            findings.extend(AIQualityReviewer(self.client).review(questionnaire))

        return questionnaire, notes, findings
