"""PDF parser (Module 1).

Purpose
-------
Extract text lines from a PDF questionnaire (via PyMuPDF) and structure them
with the :class:`QuestionnaireParser`.

Inputs
------
Path to a ``.pdf`` file.

Outputs
-------
A raw :class:`~xlsform_architect.models.Questionnaire`.

Notes
-----
Only text-based PDFs are supported (scanned/image PDFs would require OCR,
which is out of scope for a dependency-light standalone tool).

Example
-------
>>> qn = PdfParser().parse("survey.pdf")   # doctest: +SKIP
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Union

from ..models import Questionnaire
from .questionnaire_parser import QuestionnaireParser


class PdfParser:
    """Parse PDF questionnaires."""

    def __init__(self) -> None:
        self.text_parser = QuestionnaireParser()

    def parse(self, path: Union[str, Path]) -> Questionnaire:
        lines = self.extract_lines(path)
        return self.text_parser.parse_lines(lines)

    def extract_lines(self, path: Union[str, Path]) -> List[str]:
        try:
            import fitz  # PyMuPDF
        except ImportError as exc:  # pragma: no cover
            raise ImportError("PyMuPDF is required to parse PDF files "
                              "(pip install PyMuPDF).") from exc

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {path}")

        lines: List[str] = []
        doc = fitz.open(str(path))
        try:
            for page in doc:
                text = page.get_text("text")
                for raw in text.splitlines():
                    stripped = raw.strip()
                    if stripped:
                        lines.append(stripped)
        finally:
            doc.close()
        return lines
