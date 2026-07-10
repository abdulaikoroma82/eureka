"""Application controller / workflow (the orchestration layer).

Purpose
-------
Tie the whole pipeline together end-to-end:

    parse -> compile (rule engine) -> validate -> export XLSForm
          -> build the supporting artefacts (data dictionary, assumption log,
             logic map, validation report, version history)

This is the single entry point used by both the CLI (``main.py``) and the
Streamlit UI, so behaviour is identical across interfaces.

Inputs
------
* A file path OR a raw :class:`Questionnaire` OR a JSON-style ``dict``.
* Optional overrides: form title/id/version, survey category, output dir.

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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

from ..engine.knowledge_base import KnowledgeBase
from ..engine.rule_engine import RuleEngine
from ..models import Questionnaire
from ..parsers.factory import parse_file
from ..validation.report_generator import ReportGenerator, ValidationReport
from ..validation.validator import Validator
from ..xlsform.exporter import XLSFormExporter
from .artifacts import ArtifactBuilder
from .config import CONFIG

# Step labels surfaced to the UI (Module 10 processing steps).
STEP_LABELS = [
    "Reading questionnaire",
    "Identifying questions",
    "Applying rules",
    "Building XLSForm",
    "Validating output",
]

ProgressCallback = Callable[[str, str], None]  # (step_label, status)


@dataclass
class WorkflowResult:
    """Everything produced by a single run."""

    questionnaire: Questionnaire
    report: ValidationReport
    assumptions: List[str] = field(default_factory=list)
    outputs: Dict[str, Path] = field(default_factory=dict)
    xlsform_bytes: bytes = b""

    @property
    def is_valid(self) -> bool:
        return self.report.is_valid


class Workflow:
    """End-to-end orchestration controller."""

    def __init__(self, knowledge: Optional[KnowledgeBase] = None) -> None:
        self.kb = knowledge or KnowledgeBase.load()
        self.engine = RuleEngine(self.kb)
        self.validator = Validator()
        self.exporter = XLSFormExporter()
        self.reporter = ReportGenerator()
        self.artifacts = ArtifactBuilder(self.kb)

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

    # ------------------------------------------------------------------
    def _run(self, questionnaire: Questionnaire, *,
             form_title: Optional[str] = None,
             form_id: Optional[str] = None,
             version: Optional[str] = None,
             category: Optional[str] = None,
             output_dir: Optional[Union[str, Path]] = None,
             write_outputs: bool = True,
             source_name: str = "questionnaire",
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

        # --- compile (rule engine) -------------------------------------
        self._emit(progress, STEP_LABELS[1], "running")
        self._emit(progress, STEP_LABELS[1], "done")
        self._emit(progress, STEP_LABELS[2], "running")
        questionnaire, notes = self.engine.compile(questionnaire)
        self._emit(progress, STEP_LABELS[2], "done")

        # --- build XLSForm ---------------------------------------------
        self._emit(progress, STEP_LABELS[3], "running")
        xls_bytes = self.exporter.export_bytes(questionnaire)
        self._emit(progress, STEP_LABELS[3], "done")

        # --- validate --------------------------------------------------
        self._emit(progress, STEP_LABELS[4], "running")
        report = self.validator.validate(questionnaire)
        self._emit(progress, STEP_LABELS[4], "done")

        result = WorkflowResult(questionnaire=questionnaire, report=report,
                                assumptions=notes, xlsform_bytes=xls_bytes)

        if write_outputs:
            out_dir = Path(output_dir) if output_dir else CONFIG.output_dir
            result.outputs = self._write_all(questionnaire, report, notes,
                                              out_dir, source_name)
        return result

    # ------------------------------------------------------------------
    def _write_all(self, qn: Questionnaire, report: ValidationReport,
                   notes: List[str], out_dir: Path, source_name: str) -> Dict[str, Path]:
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        base = qn.settings.form_id or "form"
        folder = out_dir / f"{base}_{stamp}"
        folder.mkdir(parents=True, exist_ok=True)

        outputs: Dict[str, Path] = {}

        # 1. XLSForm.
        outputs["xlsform"] = self.exporter.export(qn, folder / f"{base}.xlsx")
        # 2. Data dictionary.
        outputs["data_dictionary"] = self.artifacts.write_data_dictionary(
            qn, folder / f"{base}_data_dictionary.xlsx")
        # 3. Validation report (PDF).
        outputs["validation_report"] = self.reporter.to_pdf(
            report, qn, folder / "QA_Report.pdf")
        # 4. Assumption log.
        assumption_path = folder / "assumption_log.md"
        assumption_path.write_text(
            self.artifacts.assumption_log_markdown(qn, notes), encoding="utf-8")
        outputs["assumption_log"] = assumption_path
        # 5. Logic map.
        logic_path = folder / "logic_map.md"
        logic_path.write_text(self.artifacts.logic_map_markdown(qn), encoding="utf-8")
        outputs["logic_map"] = logic_path
        # 6. Version history (append-only, at the output-dir root).
        outputs["version_history"] = self.artifacts.append_version_history(
            out_dir / "version_history.json", qn, source_name,
            report.is_valid, len(report.errors))

        outputs["folder"] = folder
        return outputs

    # ------------------------------------------------------------------
    @staticmethod
    def _emit(progress: Optional[ProgressCallback], step: str, status: str) -> None:
        if progress is not None:
            progress(step, status)
