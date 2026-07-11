"""AI pipeline orchestrator (optional AI layer).

Purpose
-------
Run the enabled AI-assisted features over a compiled questionnaire, in two
stages that mirror the two moments AI can usefully contribute:

**Stage 1 - :meth:`run`, before export/validation:**

    1. Type-classification fallback (may change a question's type, so it
       runs first - everything downstream should see the corrected type)
    2. Skip/condition logic fallback (adds ``relevant`` conditions)
    3. Domain-aware constraint synthesis (adds single-field ``constraint``
       bounds to questions the deterministic engine left unconstrained,
       guided by the user's optional survey-context description; runs
       before the cross-field pass so cross-field additions can combine
       on top of these)
    4. Cross-field constraint suggestions (adds ``constraint`` conditions
       spanning two questions - a job the deterministic constraint engine
       structurally cannot do, since it only ever looks at one question)
    5. Translation (labels are final by now, so translations are accurate;
       never overwrites a translation you already supplied; previously-
       translated labels are served from a local cache)
    6. Advisory suggestion features - question grouping, question
       rewording, choice-list ordering, variable-name suggestions. These
       NEVER mutate the questionnaire: each produces
       :class:`~xlsform_studio.ai.suggestions.AISuggestion` objects
       (collected on :attr:`suggestions`) for a human to accept or reject;
       accepted ones are applied by :func:`~xlsform_studio.ai.
       suggestions.apply_suggestions`.
    7. Quality review (reads the fully-settled form last; advisory findings
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
from .domain_constraints import AIDomainConstraintSynthesizer
from .enumerator_notes import AIEnumeratorNoteSuggester
from .finding_explainer import AIFindingExplainer
from .grouping import AIGroupingSuggester
from .indicators import AIIndicatorMapper
from .naming import AINamingSuggester
from .quality_reviewer import AIQualityReviewer
from .rewording import AIRewordingSuggester
from .skip_logic import AISkipLogicResolver
from .suggestions import AISuggestion
from .translator import AITranslator
from .type_classifier import AITypeClassifier

_log = get_logger("ai.pipeline")


class AIPipeline:
    """Run the enabled AI features over a compiled questionnaire."""

    def __init__(self, client: Optional[DeepSeekClient]) -> None:
        self.client = client
        #: Advisory suggestions collected by the most recent :meth:`run`
        #: (grouping, rewording, choice ordering, naming). Never applied
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

        if self._wants(config, "classify"):
            notes.extend(AITypeClassifier(self.client).classify(questionnaire))

        if self._wants(config, "skip_logic"):
            notes.extend(AISkipLogicResolver(self.client).resolve(questionnaire))

        if self._wants(config, "domain_constraints"):
            notes.extend(AIDomainConstraintSynthesizer(self.client)
                        .suggest(questionnaire, config.survey_context))

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
        if self._wants(config, "naming"):
            self._collect(notes, AINamingSuggester(self.client)
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
    def narrate(self, questionnaire: Questionnaire, quality, duration,
                report: ValidationReport, config: AIConfig) -> List[str]:
        """Attach an AI executive summary to *report* (Hybrid H1).

        Runs post-validation, after the deterministic quality index and
        duration estimate exist - AI narrates those audited numbers, it
        never computes them. No-op under the same conditions as
        :meth:`run`.
        """
        if not self._wants(config, "narrative"):
            return []
        if self.client is None or not self.client.available:
            return []
        from .narrative import AIQualityNarrator
        narrative, notes = AIQualityNarrator(self.client).narrate(
            questionnaire, quality, duration, report)
        if narrative:
            report.narrative = narrative
        return notes

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
