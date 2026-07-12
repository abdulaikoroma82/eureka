"""Application controller / workflow (the orchestration layer).

Purpose
-------
Tie the whole pipeline together end-to-end (AI-first):

    parse (deterministic scaffold)
          -> author with AI (drafts every field: type, name, label, logic,
             constraints, choices)
          -> enforce standards (deterministic: choice normalisation)
          -> [optional AI enrichment] -> validate (deterministic)
          -> export XLSForm -> build the supporting artefacts (data
             dictionary, assumption log, logic map, validation report,
             version history)

This is the single entry point used by both the CLI (``main.py``) and the
Streamlit UI, so behaviour is identical across interfaces.

AI authoring is essential, not optional: the model drafts the whole form
and the deterministic rules bracket it - the parser lays out the scaffold,
and the standards enforcer plus validators check the AI stayed on-standard.
A run therefore requires a configured DeepSeek API key and fails loudly
(:class:`~xlsform_studio.ai.client.AIError`) without one; there is no
offline authoring fallback in the shipped product. The legacy deterministic
rule-engine compiler survives only as a standards/test seam, reachable via
``authoring="deterministic"`` (or ``XLSFS_AUTHORING``), never selected by
the UI or CLI.

The optional AI enrichment step (translation, quality review, narrative,
advisory suggestions) still runs only when an
:class:`~xlsform_studio.ai.config.AIConfig` with the relevant feature
enabled is passed in; it refines the AI-authored form, never re-authors it.

Inputs
------
* A file path OR a raw :class:`Questionnaire` OR a JSON-style ``dict``.
* Optional overrides: form title/id/version, survey category, output dir.
* Optional ``ai_config`` / ``ai_client`` for the AI enrichment step.

Outputs
-------
A :class:`WorkflowResult` carrying the compiled questionnaire, the validation
report, the assumption notes and the paths of every artefact written.

Example
-------
>>> wf = Workflow()
>>> result = wf.run_from_dict({"settings": {"form_title": "Demo"},
...     "survey": [{"question": "Age"}]})          # doctest: +SKIP
>>> result.report.is_valid                          # doctest: +SKIP
True
"""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

from ..ai.client import DeepSeekClient
from ..ai.config import AIConfig
from ..ai.document_writer import DocumentProse
from ..ai.form_author import AIFormAuthor
from ..ai.pipeline import AIPipeline
from ..ai.suggestions import AISuggestion, apply_suggestions
from ..analysis.design_intelligence import (DesignIntelligence,
                                            SurveyDesignScore)
from ..analysis.duration import DurationEstimate, DurationEstimator
from ..analysis.quality_score import QualityIndex, QualityScorer
from ..engine.choice_normalizer import ChoiceNormalizer
from ..engine.knowledge_base import KnowledgeBase
from ..engine.rule_engine import RuleEngine
from ..models import Questionnaire
from ..parsers.factory import parse_file
from ..validation.report_generator import ReportGenerator, ValidationReport
from ..validation.validator import Validator
from ..xlsform.exporter import XLSFormExporter
from .artifacts import ArtifactBuilder
from .config import CONFIG
from .logic_flow import LogicFlowBuilder
from .provenance import (SIDECAR_SUFFIX, read_model_sidecar,
                         write_model_sidecar)
from .review import ReviewRow, apply_review_edits, build_review_table
from .roundtrip import reconcile
from .verification_checklist import VerificationChecklistBuilder

# Step labels surfaced to the UI. In the AI-first pipeline the AI author
# drafts the whole form; deterministic rules then enforce standards and
# validate.
STEP_LABELS = [
    "Reading questionnaire",
    "Drafting the XLSForm with AI",
    "Enforcing standards",
    "Building XLSForm",
    "Validating output",
]

#: Authoring strategy. "ai" (the product default) requires a DeepSeek client
#: and drafts every field with the model; "deterministic" runs the legacy
#: rule-engine compiler instead and exists only as a test/standards seam
#: (the shipped UI and CLI never select it, so the product has no offline
#: authoring fallback); "import" skips authoring entirely and treats the
#: model as already authoritative - used by round-trip re-import, where the
#: form was authored on a previous run and only edited since. Overridable
#: per-run or via ``XLSFS_AUTHORING``.
DEFAULT_AUTHORING = "ai"

ProgressCallback = Callable[[str, str], None]  # (step_label, status)


@dataclass
class WorkflowResult:
    """Everything produced by a single run."""

    questionnaire: Questionnaire
    report: ValidationReport
    assumptions: List[str] = field(default_factory=list)
    outputs: Dict[str, Path] = field(default_factory=dict)
    xlsform_bytes: bytes = b""
    #: Deployment platform the run targeted ("" = generic XLSForm).
    target: str = ""
    #: True if any AI feature actually ran (key configured and enabled).
    ai_ran: bool = False
    #: Advisory AI suggestions (grouping, rewording, choice ordering,
    #: naming) awaiting human accept/reject - never applied automatically.
    ai_suggestions: List[AISuggestion] = field(default_factory=list)
    #: Deterministic Form Quality Index (always computed).
    quality: Optional[QualityIndex] = None
    #: Deterministic interview-duration / burden estimate (always computed).
    duration: Optional[DurationEstimate] = None
    #: Deterministic Survey Design Score - the methodological/scientific-
    #: quality assessment (always computed; folds in AI-reviewer findings when
    #: those features ran, but never requires them).
    design: Optional[SurveyDesignScore] = None
    #: Objective-coverage matrix (markdown; "" unless the AI "coverage"
    #: feature ran with objectives supplied).
    coverage_matrix: str = ""
    #: Draft indicator matrix (markdown; "" unless the AI "indicators"
    #: feature produced one).
    indicator_matrix: str = ""
    #: Every heuristic type/choice-list/relevant/constraint decision the
    #: engine made, as an editable review row - see
    #: :mod:`~xlsform_studio.app.review`. Nothing here has been applied or
    #: blocked anything; it is purely for a human to inspect and, via
    #: :meth:`Workflow.apply_review_edits`, approve or correct.
    review_table: List[ReviewRow] = field(default_factory=list)
    #: AI-written framing prose for the supporting documents (the "documents"
    #: feature). All-empty unless AI ran with that feature enabled; the
    #: deterministic builders slot each block into a labelled position and
    #: render unchanged when it is empty.
    document_prose: DocumentProse = field(default_factory=DocumentProse)

    @property
    def is_valid(self) -> bool:
        return self.report.is_valid


class Workflow:
    """End-to-end orchestration controller."""

    def __init__(self, knowledge: Optional[KnowledgeBase] = None,
                 ai_client: Optional[DeepSeekClient] = None) -> None:
        self.kb = knowledge or KnowledgeBase.load()
        self.engine = RuleEngine(self.kb)
        # Validation must use the SAME knowledge base as compilation, so a
        # custom rules directory / domain packs govern the platform checks
        # and compatibility matrix too - not just the rule engine.
        self.validator = Validator(knowledge=self.kb)
        self.exporter = XLSFormExporter()
        self.reporter = ReportGenerator()
        self.artifacts = ArtifactBuilder(self.kb)
        #: Optional AI client. If None, callers may still pass one per-run
        #: via ``ai_client=`` on run_from_file/run_from_dict/run.
        self.ai_client = ai_client

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------
    def run_from_file(self, path: Union[str, Path], **kwargs) -> WorkflowResult:
        progress = kwargs.get("progress")
        self._emit(progress, STEP_LABELS[0], "running")
        questionnaire = parse_file(path)
        self._emit(progress, STEP_LABELS[0], "done")
        kwargs.setdefault("source_name", Path(path).name)
        return self._run(questionnaire, **kwargs)

    def run_from_dict(self, data: Dict, **kwargs) -> WorkflowResult:
        progress = kwargs.get("progress")
        self._emit(progress, STEP_LABELS[0], "running")
        questionnaire = Questionnaire.from_dict(data)
        self._emit(progress, STEP_LABELS[0], "done")
        kwargs.setdefault("source_name", "inline-json")
        return self._run(questionnaire, **kwargs)

    def run(self, questionnaire: Questionnaire, **kwargs) -> WorkflowResult:
        return self._run(questionnaire, **kwargs)

    def run_roundtrip(self, edited_path: Union[str, Path],
                      prior_model: Union[str, Path, Questionnaire],
                      **kwargs) -> WorkflowResult:
        """Re-import an edited XLSForm and rebuild, preserving provenance.

        *edited_path* is an XLSForm someone exported from a previous run and
        edited since; *prior_model* is that run's provenance sidecar (a
        ``*_model.json`` path) or the :class:`Questionnaire` itself. The
        edited form is parsed deterministically - **never** re-authored by
        AI - and reconciled field-by-field against the prior model
        (:func:`~xlsform_studio.app.roundtrip.reconcile`): unchanged fields
        keep their confidence, changed fields become high-confidence human
        reviews, new questions are flagged. The full documentation package
        (and a refreshed sidecar) is then rebuilt from the merged model.
        """
        progress = kwargs.get("progress")
        self._emit(progress, STEP_LABELS[0], "running")
        edited = parse_file(edited_path)
        prior = (prior_model if isinstance(prior_model, Questionnaire)
                 else read_model_sidecar(prior_model))
        merged, notes = reconcile(edited, prior)
        # A re-imported form carries its own settings; keep the prior form's
        # identity when the edit didn't set one.
        if not merged.settings.form_id:
            merged.settings.form_id = prior.settings.form_id
        if merged.settings.form_title in ("", "Untitled Form"):
            merged.settings.form_title = prior.settings.form_title
        self._emit(progress, STEP_LABELS[0], "done")
        kwargs.setdefault("source_name", Path(edited_path).name)
        kwargs.pop("authoring", None)          # import mode is mandatory here
        return self._run(merged, authoring="import", extra_notes=notes,
                         **kwargs)

    # ------------------------------------------------------------------
    def _run(self, questionnaire: Questionnaire, *,
             form_title: Optional[str] = None,
             form_id: Optional[str] = None,
             version: Optional[str] = None,
             category: Optional[str] = None,
             target: Optional[str] = None,
             output_dir: Optional[Union[str, Path]] = None,
             write_outputs: bool = True,
             source_name: str = "questionnaire",
             ai_config: Optional[AIConfig] = None,
             ai_client: Optional[DeepSeekClient] = None,
             authoring: Optional[str] = None,
             survey_context: str = "",
             path_analysis: bool = True,
             extra_notes: Optional[List[str]] = None,
             progress: Optional[ProgressCallback] = None) -> WorkflowResult:

        # Apply overrides.
        if form_title:
            questionnaire.settings.form_title = form_title
        if form_id:
            questionnaire.settings.form_id = form_id
        if version:
            questionnaire.settings.version = version
        if category:
            questionnaire.category = category
        target = (target or "").lower() or None

        ai_config = ai_config or AIConfig.disabled()
        client = ai_client if ai_client is not None else self.ai_client
        mode = (authoring or os.environ.get("XLSFS_AUTHORING")
                or DEFAULT_AUTHORING).lower()

        # --- author the XLSForm ----------------------------------------
        # AI-first (the product default): the model drafts every field
        # (type, name, label, logic, constraints, choices). The legacy
        # deterministic rule engine is only reachable via ``authoring=
        # "deterministic"`` and exists as a standards/test seam - the
        # shipped UI and CLI never select it, so a run without a configured
        # DeepSeek key fails loudly rather than silently degrading.
        self._emit(progress, STEP_LABELS[1], "running")
        if mode == "import":
            # Round-trip re-import: the form was authored on a previous run
            # and only edited since, so the incoming model is authoritative -
            # re-authoring it would overwrite the human's edits. Any
            # reconciliation notes are supplied via ``extra_notes``.
            notes = []
        elif mode == "deterministic":
            questionnaire, notes = self.engine.compile(questionnaire)
        else:
            notes = AIFormAuthor(client, self.kb).author(
                questionnaire, target=target, survey_context=survey_context)
        if extra_notes:
            notes = list(extra_notes) + notes
        self._emit(progress, STEP_LABELS[1], "done")

        # --- deterministic standards enforcement -----------------------
        # Rules keep the AI on-standard: consolidate exactly-duplicate
        # choice lists (provably safe; logged). Remaining standards checks
        # are reported by the validator below.
        self._emit(progress, STEP_LABELS[2], "running")
        notes.extend(ChoiceNormalizer().normalize(questionnaire))
        self._emit(progress, STEP_LABELS[2], "done")

        # --- optional AI enrichment (translation, quality review, ...) --
        # These supplementary passes stay opt-in via ai_config; they only
        # ever annotate or refine the AI-authored form, never re-author it.
        ai_pipeline = AIPipeline(client)
        questionnaire, ai_notes, ai_findings = ai_pipeline.run(
            questionnaire, ai_config)
        notes.extend(ai_notes)

        # --- build XLSForm (in the target platform's dialect) -----------
        self._emit(progress, STEP_LABELS[3], "running")
        xls_bytes = self.exporter.export_bytes(questionnaire, target=target)
        self._emit(progress, STEP_LABELS[3], "done")

        # --- validate (generic + the chosen platform's standards) -------
        self._emit(progress, STEP_LABELS[4], "running")
        report = self.validator.validate(questionnaire, target=target,
                                         path_analysis=path_analysis)
        report.findings.extend(ai_findings)
        # AI may add a plain-English explanation to the findings above -
        # this must run AFTER validation produces them; it never changes
        # the findings themselves, only annotates them (see AIFindingExplainer).
        notes.extend(ai_pipeline.explain_findings(report, ai_config))

        # Deterministic analysis: always computed, costs nothing, and the
        # optional AI narrative below only ever NARRATES these numbers.
        quality = QualityScorer().score(questionnaire, report)
        duration = DurationEstimator().estimate(questionnaire)
        notes.extend(ai_pipeline.narrate(questionnaire, quality, duration,
                                         report, ai_config))
        # AI co-writes the supporting documents' framing prose, grounded in
        # the audited metrics above. Fails open to empty prose; the
        # deterministic builders slot it in and render unchanged without it.
        document_prose, doc_notes = ai_pipeline.write_documents(
            questionnaire, quality, duration, report, ai_config)
        notes.extend(doc_notes)
        # Survey Design Score: the deterministic methodological assessment.
        # Folds in the coverage matrix (if the AI coverage feature ran) and
        # any AI-reviewer findings already in the report, but needs neither.
        design = DesignIntelligence().score(
            questionnaire, report, duration=duration,
            coverage_matrix=ai_pipeline.coverage_matrix)
        self._emit(progress, STEP_LABELS[4], "done")

        result = WorkflowResult(questionnaire=questionnaire, report=report,
                                assumptions=notes, xlsform_bytes=xls_bytes,
                                target=target or "",
                                ai_ran=bool(client and client.available
                                           and ai_config.any_feature_enabled),
                                ai_suggestions=list(ai_pipeline.suggestions),
                                quality=quality, duration=duration,
                                design=design,
                                coverage_matrix=ai_pipeline.coverage_matrix,
                                indicator_matrix=ai_pipeline.indicator_matrix,
                                review_table=build_review_table(questionnaire),
                                document_prose=document_prose)

        if write_outputs:
            out_dir = Path(output_dir) if output_dir else CONFIG.output_dir
            result.outputs = self._write_all(questionnaire, report, notes,
                                              out_dir, source_name, target,
                                              quality=quality,
                                              duration=duration,
                                              prose=document_prose,
                                              design=design)
            if result.coverage_matrix:
                matrix_path = result.outputs["folder"] / "coverage_matrix.md"
                matrix_path.write_text(result.coverage_matrix,
                                       encoding="utf-8")
                result.outputs["coverage_matrix"] = matrix_path
            if result.indicator_matrix:
                ind_path = result.outputs["folder"] / "indicator_matrix.md"
                ind_path.write_text(result.indicator_matrix,
                                    encoding="utf-8")
                result.outputs["indicator_matrix"] = ind_path
        return result

    # ------------------------------------------------------------------
    def apply_ai_suggestions(self, result: WorkflowResult,
                             accepted: List[AISuggestion],
                             output_dir: Optional[Union[str, Path]] = None,
                             write_outputs: bool = False,
                             source_name: str = "questionnaire"
                             ) -> WorkflowResult:
        """Apply human-accepted AI suggestions, then re-export + re-validate.

        Each suggestion is re-validated at apply time (see
        :func:`~xlsform_studio.ai.suggestions.apply_suggestions`);
        anything stale or invalid is rejected with a note rather than
        half-applied. Advisory ``ai_review`` findings from the original run
        are carried over unchanged - re-validation only refreshes the
        deterministic findings.
        """
        qn = result.questionnaire
        result.assumptions.extend(apply_suggestions(qn, accepted))

        result.xlsform_bytes = self.exporter.export_bytes(
            qn, target=result.target or None)
        preserved = [f for f in result.report.findings
                     if f.category == "ai_review"]
        narrative = result.report.narrative
        result.report = self.validator.validate(qn, target=result.target or None)
        result.report.findings.extend(preserved)
        result.report.narrative = narrative
        result.quality = QualityScorer().score(qn, result.report)
        result.duration = DurationEstimator().estimate(qn)
        result.design = DesignIntelligence().score(
            qn, result.report, duration=result.duration,
            coverage_matrix=result.coverage_matrix)
        # A "naming" suggestion can rename a question referenced by a
        # review row; rebuild rather than risk a stale question name.
        result.review_table = build_review_table(qn)

        if write_outputs:
            out_dir = Path(output_dir) if output_dir else CONFIG.output_dir
            result.outputs = self._write_all(qn, result.report,
                                              result.assumptions, out_dir,
                                              source_name, result.target or None,
                                              quality=result.quality,
                                              duration=result.duration,
                                              prose=result.document_prose,
                                              design=result.design)
        return result

    # ------------------------------------------------------------------
    def apply_review_edits(self, result: WorkflowResult,
                           edits: Dict[Tuple[str, str], str],
                           output_dir: Optional[Union[str, Path]] = None,
                           write_outputs: bool = False,
                           source_name: str = "questionnaire"
                           ) -> WorkflowResult:
        """Apply human-reviewed type/choice-list/relevant/constraint values,
        then re-export + re-validate - the same "compile, review, rebuild"
        pattern as :meth:`apply_ai_suggestions`.

        *edits* maps ``(question_name, field_name) -> value`` for every row
        the reviewer looked at, whether they changed it (an edit) or left
        it as shown (an approval) - see :mod:`~xlsform_studio.app.review`.
        """
        qn = result.questionnaire
        result.assumptions.extend(apply_review_edits(qn, edits))
        result.review_table = build_review_table(qn)

        result.xlsform_bytes = self.exporter.export_bytes(
            qn, target=result.target or None)
        preserved = [f for f in result.report.findings
                     if f.category == "ai_review"]
        narrative = result.report.narrative
        result.report = self.validator.validate(qn, target=result.target or None)
        result.report.findings.extend(preserved)
        result.report.narrative = narrative
        result.quality = QualityScorer().score(qn, result.report)
        result.duration = DurationEstimator().estimate(qn)
        result.design = DesignIntelligence().score(
            qn, result.report, duration=result.duration,
            coverage_matrix=result.coverage_matrix)

        if write_outputs:
            out_dir = Path(output_dir) if output_dir else CONFIG.output_dir
            result.outputs = self._write_all(qn, result.report,
                                              result.assumptions, out_dir,
                                              source_name, result.target or None,
                                              quality=result.quality,
                                              duration=result.duration,
                                              prose=result.document_prose,
                                              design=result.design)
        return result

    # ------------------------------------------------------------------
    def _write_all(self, qn: Questionnaire, report: ValidationReport,
                   notes: List[str], out_dir: Path, source_name: str,
                   target: Optional[str] = None,
                   quality: Optional[QualityIndex] = None,
                   duration: Optional[DurationEstimate] = None,
                   prose: Optional[DocumentProse] = None,
                   design: Optional[SurveyDesignScore] = None
                   ) -> Dict[str, Path]:
        prose = prose or DocumentProse()
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        base = qn.settings.form_id or "form"
        folder = out_dir / f"{base}_{stamp}"
        folder.mkdir(parents=True, exist_ok=True)

        outputs: Dict[str, Path] = {}

        # 1. XLSForm (written in the target platform's dialect).
        outputs["xlsform"] = self.exporter.export(qn, folder / f"{base}.xlsx",
                                                  target=target)
        # 2. Data dictionary.
        outputs["data_dictionary"] = self.artifacts.write_data_dictionary(
            qn, folder / f"{base}_data_dictionary.xlsx")
        # 3. Validation report (PDF), incl. quality index + duration estimate.
        outputs["validation_report"] = self.reporter.to_pdf(
            report, qn, folder / "QA_Report.pdf", quality=quality,
            duration=duration, design=design)
        # 4. Assumption log + its prioritized verification checklist (the
        #    checklist reorganises the same entries by review priority; the
        #    log remains the complete ordered record).
        assumption_path = folder / "assumption_log.md"
        assumption_path.write_text(
            self.artifacts.assumption_log_markdown(qn, notes), encoding="utf-8")
        outputs["assumption_log"] = assumption_path
        outputs["assumptions_to_verify"] = VerificationChecklistBuilder().write(
            qn, notes, folder / "assumptions_to_verify.md",
            intro=prose.assumptions_intro)
        # 5. Logic map (+ the skip-pattern flowchart as Graphviz DOT, when
        #    the form has any skip logic to draw).
        logic_path = folder / "logic_map.md"
        logic_path.write_text(
            self.artifacts.logic_map_markdown(qn, overview=prose.logic_overview),
            encoding="utf-8")
        outputs["logic_map"] = logic_path
        dot = LogicFlowBuilder().to_dot(qn)
        if dot:
            dot_path = folder / "logic_flow.dot"
            dot_path.write_text(dot, encoding="utf-8")
            outputs["logic_flow"] = dot_path
        # 6. Survey implementation package (enumerator guide, variable
        #    specification, collection plan) - all derived deterministically.
        guide_path = folder / "enumerator_guide.md"
        guide_path.write_text(
            self.artifacts.enumerator_guide_markdown(
                qn, duration=duration, intro=prose.enumerator_intro),
            encoding="utf-8")
        outputs["enumerator_guide"] = guide_path
        outputs["variable_specification"] = \
            self.artifacts.write_variable_specification(
                qn, folder / f"{base}_variable_specification.xlsx")
        plan_path = folder / "collection_plan.md"
        plan_path.write_text(
            self.artifacts.collection_plan_markdown(
                qn, duration=duration, overview=prose.collection_plan_overview),
            encoding="utf-8")
        outputs["collection_plan"] = plan_path
        outputs["survey_instrument"] = self.artifacts.write_survey_instrument_docx(
            qn, folder / f"{base}_survey_instrument.docx", duration=duration,
            intro=prose.instrument_intro)
        # 7. Version history (append-only, at the output-dir root).
        outputs["version_history"] = self.artifacts.append_version_history(
            out_dir / "version_history.json", qn, source_name,
            report.is_valid, len(report.errors), target=target or "")
        # 8. Model snapshot (provenance sidecar): the complete model incl.
        #    per-field confidence and the assumptions log, so an edited
        #    XLSForm can later be re-imported without losing either (see
        #    Workflow.run_roundtrip).
        outputs["model_snapshot"] = write_model_sidecar(
            qn, folder / f"{base}{SIDECAR_SUFFIX}")
        # 9. Survey Design Score report (methodological assessment).
        if design is not None:
            design_path = folder / "survey_design_report.md"
            design_path.write_text(design.to_markdown(), encoding="utf-8")
            outputs["survey_design_report"] = design_path

        outputs["folder"] = folder
        return outputs

    # ------------------------------------------------------------------
    @staticmethod
    def _emit(progress: Optional[ProgressCallback], step: str, status: str) -> None:
        if progress is not None:
            progress(step, status)
