"""Validation report generator (part of Module 9).

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
from typing import Dict, List, Union

from ..models import Questionnaire

_LEVEL_ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass
class Finding:
    """A single validation result.

    level:    "error" | "warning" | "info"
    category: "structure" | "logic" | "deployment" | ...
    message:  human readable description
    location: variable / list name the finding refers to (optional)
    """

    level: str
    category: str
    message: str
    location: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {"level": self.level, "category": self.category,
                "message": self.message, "location": self.location}


@dataclass
class ValidationReport:
    """Aggregated validation outcome."""

    findings: List[Finding] = field(default_factory=list)
    compatibility: Dict[str, bool] = field(default_factory=dict)
    #: True when the pyxform deep check actually ran (pyxform installed).
    deep_ran: bool = False

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
                      key=lambda f: (_LEVEL_ORDER.get(f.level, 9), f.category))


class ReportGenerator:
    """Render a :class:`ValidationReport` to Markdown / PDF."""

    def to_markdown(self, report: ValidationReport, questionnaire: Questionnaire) -> str:
        s = questionnaire.settings
        lines: List[str] = []
        lines.append("# XLSForm Architect - QA Validation Report")
        lines.append("")
        lines.append(f"**Form:** {s.form_title}  ")
        lines.append(f"**Form id:** {s.form_id}  ")
        lines.append(f"**Version:** {s.version}  ")
        lines.append(f"**Generated:** {_dt.datetime.now():%Y-%m-%d %H:%M}  ")
        lines.append("")
        status = "PASSED" if report.is_valid else "FAILED"
        lines.append(f"## Overall status: {status}")
        lines.append("")
        lines.append(report.summary())
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

        # Findings grouped by level.
        for level in ("error", "warning", "info"):
            group = [f for f in report.findings if f.level == level]
            if not group:
                continue
            lines.append(f"## {level.capitalize()}s ({len(group)})")
            lines.append("")
            for f in group:
                loc = f" [`{f.location}`]" if f.location else ""
                lines.append(f"- **{f.category}**{loc}: {f.message}")
            lines.append("")

        if report.is_valid:
            lines.append("_No blocking errors. The form is ready for deployment._")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    def to_pdf(self, report: ValidationReport, questionnaire: Questionnaire,
               path: Union[str, Path]) -> Path:
        """Write a QA report PDF.  Falls back to .txt if PyMuPDF is missing."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        markdown = self.to_markdown(report, questionnaire)
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
