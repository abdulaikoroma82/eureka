"""Validation report generator.

Purpose
-------
Define the shared :class:`Finding` type, aggregate findings from all
validators into a :class:`ValidationReport`, and render that report to
Markdown and PDF (``QA_Report.pdf``).

Inputs
------
Lists of :class:`Finding` objects plus the :class:`Questionnaire`.

Outputs
-------
* ``ValidationReport`` object (with ``is_valid`` / ``summary``).
* Markdown text.
* PDF file on disk (via PyMuPDF; falls back to a ``.txt`` if PyMuPDF is
  unavailable so the pipeline never hard-fails).

Example
-------
>>> r = ValidationReport(findings=[Finding("error", "logic", "boom")])
>>> r.is_valid
False
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple, Union

from ..models import Questionnaire

_LEVEL_ORDER = {"error": 0, "warning": 1, "info": 2}

#: How sure the tool is about a finding, independent of its error/warning/
#: info *level*. A "warning" can be rock-solid (an exact reference-count
#: fact) or a shot in the dark (an LLM suggestion) - level says how bad it
#: would be if true, confidence says how sure we are it's true.
#:
#: * ``confirmed``   - verified by an actual platform toolchain (pyxform
#:   converted the form to a real ODK XForm, or failed to)
#: * ``checked``      - this tool's own deterministic rule/grammar checked
#:   it exactly (structure, logic, references, syntax, path analysis)
#: * ``heuristic``    - a pattern-matched inference or AI suggestion about
#:   likely intent - correct enough to be useful, not a proof; review it
#: * ``unsupported``  - this tool could not check it (unrecognised
#:   function, deep validation unavailable/incomplete) and passed it
#:   through unchanged rather than guessing or rejecting
CONFIDENCE_LEVELS: Tuple[str, ...] = ("confirmed", "checked", "heuristic",
                                      "unsupported")
_CONFIDENCE_ORDER = {c: i for i, c in enumerate(CONFIDENCE_LEVELS)}
CONFIDENCE_LABELS: Dict[str, str] = {
    "confirmed": "Confirmed by platform toolchain",
    "checked": "Syntax/rule checked by this tool",
    "heuristic": "Heuristically inferred - review needed",
    "unsupported": "Unsupported / passed through unchanged",
}
CONFIDENCE_ICONS: Dict[str, str] = {
    "confirmed": "✅", "checked": "🔎", "heuristic": "🧭", "unsupported": "❔",
}


@dataclass
class Finding:
    """A single validation result.

    level:    "error" | "warning" | "info"
    category: "structure" | "logic" | "deployment" | ...
    message:  human readable description
    location: variable / list name the finding refers to (optional)
    explanation: optional plain-English elaboration on ``message``. Rules
        remain the sole authority on level/category/message/location; this
        field is purely additive commentary, set only by the optional AI
        "explain findings" pass (never changes what was found, only how it
        is described to a reader).
    confidence: one of :data:`CONFIDENCE_LEVELS`. Defaults to ``"checked"``,
        the modal case for this tool's own deterministic rule validators;
        set explicitly wherever a finding is toolchain-confirmed, a fuzzy
        inference, or something the tool passed through unchecked.
    """

    level: str
    category: str
    message: str
    location: str = ""
    explanation: str = ""
    confidence: str = "checked"

    def __post_init__(self) -> None:
        if self.confidence not in CONFIDENCE_LEVELS:
            raise ValueError(
                f"Finding.confidence must be one of {CONFIDENCE_LEVELS}, "
                f"got {self.confidence!r}")

    def to_dict(self) -> Dict[str, str]:
        return {"level": self.level, "category": self.category,
                "message": self.message, "location": self.location,
                "explanation": self.explanation, "confidence": self.confidence}


@dataclass
class ValidationReport:
    """Aggregated validation outcome."""

    findings: List[Finding] = field(default_factory=list)
    compatibility: Dict[str, bool] = field(default_factory=dict)
    #: True when the pyxform deep check actually ran (pyxform installed).
    deep_ran: bool = False
    #: The deployment platform the form was validated against ("" = generic).
    target: str = ""
    #: Optional executive summary written by the AI narrative feature.
    #: Purely additive commentary: it can never change a finding or score.
    narrative: str = ""

    @property
    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> List[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        return (f"{len(self.errors)} error(s), {len(self.warnings)} warning(s), "
                f"{len(self.findings)} finding(s) total")

    def sorted_findings(self) -> List[Finding]:
        return sorted(self.findings,
                      key=lambda f: (_LEVEL_ORDER.get(f.level, 9), f.category,
                                     _CONFIDENCE_ORDER.get(f.confidence, 9)))


def _finding_line(f: Finding, label_field: str = "category") -> str:
    """One markdown bullet for a finding, tagged with its confidence icon."""
    loc = f" [`{f.location}`]" if f.location else ""
    icon = CONFIDENCE_ICONS.get(f.confidence, "")
    label = f.category if label_field == "category" else f.level
    return f"- {icon} **{label}**{loc}: {f.message}"


class ReportGenerator:
    """Render a :class:`ValidationReport` to Markdown / PDF."""

    def to_markdown(self, report: ValidationReport,
                    questionnaire: Questionnaire,
                    quality=None, duration=None) -> str:
        """Render the QA report.

        *quality* (a :class:`~xlsform_studio.analysis.quality_score.
        QualityIndex`) and *duration* (a :class:`~xlsform_studio.
        analysis.duration.DurationEstimate`) are optional so existing
        callers keep working; the workflow passes both.
        """
        s = questionnaire.settings
        lines: List[str] = []
        lines.append("# XLSForm Studio - QA Validation Report")
        lines.append("")
        lines.append(f"**Form:** {s.form_title}  ")
        lines.append(f"**Form id:** {s.form_id}  ")
        lines.append(f"**Version:** {s.version}  ")
        lines.append(f"**Generated:** {_dt.datetime.now():%Y-%m-%d %H:%M}  ")
        lines.append("")
        status = "PASSED" if report.is_valid else "FAILED"
        lines.append(f"## Overall status: {status}")
        lines.append("")
        if report.narrative:
            lines.append("## Executive summary")
            lines.append("")
            lines.append(f"_{report.narrative}_")
            lines.append("")
            lines.append("*(AI-written from the audited metrics below; "
                         "advisory only.)*")
            lines.append("")
        if quality is not None:
            lines.append(f"## Form Quality Index: {quality.overall}/100 "
                         f"({quality.rating})")
            lines.append("")
            lines.append("| Category | Score |")
            lines.append("| --- | --- |")
            for name, score in quality.categories.items():
                lines.append(f"| {name.replace('_', ' ')} | {score}/100 |")
            lines.append("")
            for ob in quality.observations:
                lines.append(f"- {ob}")
            if quality.observations:
                lines.append("")
        if duration is not None:
            lines.append("## Estimated interview duration")
            lines.append("")
            lines.append(f"**~{duration.typical_minutes:.0f} minutes** "
                         f"(range {duration.low_minutes:.0f}–"
                         f"{duration.high_minutes:.0f}) across "
                         f"{duration.question_count} question(s); "
                         f"respondent-burden risk: **{duration.burden_risk}**.")
            lines.append("")
            for note in duration.notes:
                lines.append(f"- {note}")
            if duration.notes:
                lines.append("")
        if report.target:
            lines.append(f"**Validated against:** {report.target.upper()} "
                         f"standards (plus the generic XLSForm spec)  ")
        lines.append(report.summary())
        lines.append("")
        if report.findings:
            lines.append("**Confidence key:** " + " · ".join(
                f"{CONFIDENCE_ICONS[c]} {CONFIDENCE_LABELS[c]}"
                for c in CONFIDENCE_LEVELS) + "  ")
            lines.append("")
        deep = ("Deep validation via pyxform (the ODK/Kobo engine) was run."
                if report.deep_ran else
                "Deep validation via pyxform was NOT run (pyxform not installed); "
                "standard checks only.")
        lines.append(f"_{deep}_")
        lines.append("")

        # Deployment compatibility.
        if report.compatibility:
            lines.append("## Deployment compatibility")
            lines.append("")
            lines.append("| Platform | Compatible |")
            lines.append("| --- | --- |")
            for platform, ok in report.compatibility.items():
                lines.append(f"| {platform.upper()} | {'Yes' if ok else 'No'} |")
            lines.append("")

        # Findings grouped by level. Three categories get their own named
        # sections below instead (AI review, path analysis, choice quality),
        # so they are never mistaken for the general rule checks.
        _own_section = ("ai_review", "path_analysis", "choice_quality")
        for level in ("error", "warning", "info"):
            group = [f for f in report.findings
                     if f.level == level and f.category not in _own_section]
            if not group:
                continue
            lines.append(f"## {level.capitalize()}s ({len(group)})")
            lines.append("")
            for f in group:
                lines.append(_finding_line(f, "category"))
                if f.explanation:
                    lines.append(f"  - _{f.explanation}_")
            lines.append("")

        path_group = [f for f in report.findings
                      if f.category == "path_analysis"]
        if path_group:
            lines.append(f"## Path Analysis ({len(path_group)})")
            lines.append("")
            lines.append("_Static analysis of every possible route through "
                         "the form's skip logic: does each expression's "
                         "reference actually hold a value on the paths "
                         "where it runs?_")
            lines.append("")
            for f in sorted(path_group,
                            key=lambda f: _LEVEL_ORDER.get(f.level, 9)):
                lines.append(_finding_line(f, "level"))
                if f.explanation:
                    lines.append(f"  - _{f.explanation}_")
            lines.append("")

        choice_group = [f for f in report.findings
                        if f.category == "choice_quality"]
        if choice_group:
            lines.append(f"## Choice List Quality ({len(choice_group)})")
            lines.append("")
            lines.append("_Deterministic semantic checks on every choice "
                         "list: scale completeness, logical ordering, "
                         "Other/specify pairing, and value coding._")
            lines.append("")
            for f in sorted(choice_group,
                            key=lambda f: _LEVEL_ORDER.get(f.level, 9)):
                lines.append(_finding_line(f, "level"))
                if f.explanation:
                    lines.append(f"  - _{f.explanation}_")
            lines.append("")

        ai_group = [f for f in report.findings if f.category == "ai_review"]
        if ai_group:
            lines.append(f"## AI review findings ({len(ai_group)})")
            lines.append("")
            lines.append("_Advisory only - flagged by the optional AI "
                         "quality review for a human to consider; these "
                         "never block deployment._")
            lines.append("")
            for f in ai_group:
                lines.append(_finding_line(f, "level"))
                if f.explanation:
                    lines.append(f"  - _{f.explanation}_")
            lines.append("")

        if report.is_valid:
            lines.append("_No blocking errors. The form is ready for deployment._")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    def to_pdf(self, report: ValidationReport, questionnaire: Questionnaire,
               path: Union[str, Path], quality=None, duration=None) -> Path:
        """Write a QA report PDF.  Falls back to .txt if PyMuPDF is missing."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        markdown = self.to_markdown(report, questionnaire, quality=quality,
                                    duration=duration)
        try:
            return self._pdf_via_fitz(markdown, path)
        except Exception:  # pragma: no cover - defensive fallback
            fallback = path.with_suffix(".txt")
            fallback.write_text(markdown, encoding="utf-8")
            return fallback

    def _pdf_via_fitz(self, markdown: str, path: Path) -> Path:
        import fitz  # PyMuPDF

        # Strip a little markdown for clean plain-text rendering.
        text = (markdown.replace("**", "").replace("`", "")
                .replace("# ", "").replace("## ", "").replace("### ", ""))

        doc = fitz.open()
        margin = 50
        page = doc.new_page()
        width = page.rect.width - 2 * margin
        y = margin
        line_height = 14
        font_size = 10

        for raw_line in text.split("\n"):
            # Wrap long lines to the page width.
            for line in self._wrap(raw_line, width, font_size):
                if y > page.rect.height - margin:
                    page = doc.new_page()
                    y = margin
                page.insert_text((margin, y), line, fontsize=font_size, fontname="helv")
                y += line_height
        doc.save(str(path))
        doc.close()
        return path

    @staticmethod
    def _wrap(line: str, width: float, font_size: int) -> List[str]:
        if not line:
            return [""]
        import fitz

        words = line.split(" ")
        out: List[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if fitz.get_text_length(candidate, fontname="helv", fontsize=font_size) > width and current:
                out.append(current)
                current = word
            else:
                current = candidate
        out.append(current)
        return out
