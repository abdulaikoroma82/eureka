"""AI pipeline orchestrator (enrichment layer).

Purpose
-------
Run the enabled AI *enrichment* passes over the already AI-authored form, in
two stages. Authoring itself (type, name, label, logic, constraints, choices)
happens earlier in :mod:`xlsform_studio.ai.form_author`; this module only
refines or reviews that draft, so it never re-does authoring work (type
classification, skip-logic resolution and single-field constraints are all
produced by the author and are deliberately absent here).

**Stage 1 - :meth:`run`, before export/validation:**

    1. Cross-field constraint suggestions (adds ``constraint`` conditions
       spanning two questions - e.g. an end date after a start date)
    2. Translation (labels are final by now, so translations are accurate;
       never overwrites a translation you already supplied; previously-
       translated labels are served from a local cache)
    3. Advisory suggestion features - question grouping, question
       rewording, choice-list ordering, variable-name suggestions. These
       NEVER mutate the questionnaire: each produces
       :class:`~xlsform_studio.ai.suggestions.AISuggestion` objects
       (collected on :attr:`suggestions`) for a human to accept or reject;
       accepted ones are applied by :func:`~xlsform_studio.ai.
       suggestions.apply_suggestions`.
    4. Quality review (reads the fully-settled form last; advisory findings
       only, never mutates the questionnaire)

**Stage 2 - :meth:`explain_findings`, after validation:** adds a plain-
English ``explanation`` to the deterministic validator's own findings. This
necessarily runs after :class:`~xlsform_studio.validation.validator.
Validator` has produced its authoritative result, since it explains findings
that don't exist until validation runs; it never changes what was found.

This is the single integration point :class:`~xlsform_studio.app.
workflow.Workflow` calls; both stages are a no-op with zero network activity
whenever :class:`~xlsform_studio.ai.config.AIConfig` is disabled or no
client is available, so the deterministic pipeline's behaviour is completely
unaffected by this module's existence.

Inputs
------
A compiled :class:`~xlsform_studio.models.Questionnaire`, an
:class:`~xlsform_studio.ai.config.AIConfig`, and a
:class:`~xlsform_studio.ai.client.DeepSeekClient` (or ``None``).

Outputs
-------
The questionnaire (mutated in place where features applied changes), a list
of human-readable notes (folded into the assumption log), and a list of
:class:`~xlsform_studio.validation.report_generator.Finding` (folded into
the validation report).

Example
-------
>>> from xlsform_studio.ai.config import AIConfig
>>> qn, notes, findings = AIPipeline(client=None).run(Questionnaire(), AIConfig.disabled())
>>> notes
[]
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from ..logging_config import get_logger
from ..models import Questionnaire
from ..validation.report_generator import Finding, ValidationReport
from .choice_ordering import AIChoiceOrderingSuggester
from .client import MAX_QUESTIONS_FOR_AI, DeepSeekClient
from .completeness import AICompletenessReviewer
from .config import AIConfig
from .coverage import AICoverageReviewer
from .constraint_reviewer import AICrossFieldConstraintReviewer
from .enumerator_notes import AIEnumeratorNoteSuggester
from .finding_explainer import AIFindingExplainer
from .grouping import AIGroupingSuggester
from .indicators import AIIndicatorMapper
from .quality_reviewer import AIQualityReviewer
from .rewording import AIRewordingSuggester
from .suggestions import AISuggestion
from .translator import AITranslator

_log = get_logger("ai.pipeline")


class AIPipeline:
    """Run the enabled AI features over a compiled questionnaire."""

    def __init__(self, client: Optional[DeepSeekClient]) -> None:
        self.client = client
        #: Advisory suggestions collected by the most recent :meth:`run`
        #: (grouping, rewording, choice ordering, hints). Never applied
        #: automatically - see :mod:`xlsform_studio.ai.suggestions`.
        self.suggestions: List[AISuggestion] = []
        #: Objective-coverage matrix (markdown) from the most recent
        #: :meth:`run`; "" unless the "coverage" feature produced one.
        self.coverage_matrix: str = ""
        #: Draft indicator matrix (markdown) from the most recent
        #: :meth:`run`; "" unless the "indicators" feature produced one.
        self.indicator_matrix: str = ""

    # ------------------------------------------------------------------
    def run(self, questionnaire: Questionnaire,
            config: AIConfig) -> Tuple[Questionnaire, List[str], List[Finding]]:
        notes: List[str] = []
        findings: List[Finding] = []
        self.suggestions = []
        self.coverage_matrix = ""
        self.indicator_matrix = ""

        if not config.any_feature_enabled:
            _log.debug("run skipped: no AI feature enabled")
            return questionnaire, notes, findings

        if self.client is None or not self.client.available:
            _log.warning("run skipped: AI requested (%s) but no API key "
                        "configured", ", ".join(config.features))
            notes.append("[AI] AI features were requested but no API key is "
                        "configured (DEEPSEEK_API_KEY); AI enrichment was "
                        "skipped and the deterministic result stands.")
            return questionnaire, notes, findings

        question_count = len(questionnaire.questions)
        if question_count > MAX_QUESTIONS_FOR_AI:
            _log.warning("run skipped: %d questions exceeds the %d-question "
                        "AI ceiling", question_count, MAX_QUESTIONS_FOR_AI)
            notes.append(f"[AI] This form has {question_count} questions, "
                        f"above the {MAX_QUESTIONS_FOR_AI}-question ceiling "
                        f"for AI enrichment (keeps prompts within the "
                        f"model's context window and bounds API cost per "
                        f"run); AI enrichment was skipped and the "
                        f"deterministic result stands.")
            return questionnaire, notes, findings

        _log.info("run start: features=%s questions=%d",
                 ", ".join(config.features), question_count)

        if self._wants(config, "cross_constraints"):
            notes.extend(AICrossFieldConstraintReviewer(self.client)
                        .suggest(questionnaire))

        if self._wants(config, "translate") and config.translate_languages:
            notes.extend(AITranslator(
                self.client,
                cache_path=config.translation_cache_path or None,
            ).translate(questionnaire, config.translate_languages))

        # Advisory suggestion features: collect, never apply.
        if self._wants(config, "group"):
            self._collect(notes, AIGroupingSuggester(self.client)
                          .suggest(questionnaire))
        if self._wants(config, "rewrite"):
            self._collect(notes, AIRewordingSuggester(self.client)
                          .suggest(questionnaire))
        if self._wants(config, "order"):
            self._collect(notes, AIChoiceOrderingSuggester(self.client)
                          .suggest(questionnaire))
        if self._wants(config, "instructions"):
            self._collect(notes, AIEnumeratorNoteSuggester(self.client)
                          .suggest(questionnaire))

        if self._wants(config, "completeness"):
            findings.extend(AICompletenessReviewer(self.client).review(
                questionnaire, config.survey_context))

        if self._wants(config, "coverage") and config.objectives.strip():
            matrix, cov_notes, cov_findings = AICoverageReviewer(
                self.client).review(questionnaire, config.objectives)
            self.coverage_matrix = matrix
            notes.extend(cov_notes)
            findings.extend(cov_findings)

        if self._wants(config, "indicators"):
            matrix, ind_notes = AIIndicatorMapper(self.client).map(
                questionnaire, config.survey_context)
            self.indicator_matrix = matrix
            notes.extend(ind_notes)

        if self._wants(config, "review"):
            findings.extend(AIQualityReviewer(self.client).review(
                questionnaire, config.survey_context))

        _log.info("run done: notes=%d findings=%d suggestions=%d",
                 len(notes), len(findings), len(self.suggestions))
        return questionnaire, notes, findings

    def _wants(self, config: AIConfig, feature: str) -> bool:
        """``config.wants`` with a debug trace of which feature ran/skipped."""
        wanted = config.wants(feature)
        _log.debug("feature '%s': %s", feature, "running" if wanted else "skipped")
        return wanted

    def _collect(self, notes: List[str], result) -> None:
        feature_notes, suggestions = result
        notes.extend(feature_notes)
        self.suggestions.extend(suggestions)

    # ------------------------------------------------------------------
    def explain_findings(self, report: ValidationReport,
                         config: AIConfig) -> List[str]:
        """Add plain-English explanations to already-computed findings.

        Must be called after validation has produced *report*. A no-op
        under the same conditions as :meth:`run` (disabled, or no usable
        client).
        """
        if not self._wants(config, "explain_findings"):
            return []
        if self.client is None or not self.client.available:
            return []          # already reported once by run(); avoid noise
        return AIFindingExplainer(self.client).explain(report)
