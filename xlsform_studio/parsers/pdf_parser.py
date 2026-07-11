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
A raw :class:`~xlsform_studio.models.Questionnaire`.

Notes
-----
Only text-based PDFs are supported (scanned/image PDFs would require OCR,
which is out of scope for a dependency-light standalone tool).

Example
-------
>>> qn = PdfParser().parse("survey.pdf")   # doctest: +SKIP
"""

from __future__ import annotations

import re
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

        pages: List[List[str]] = []
        doc = fitz.open(str(path))
        try:
            for page in doc:
                text = page.get_text("text")
                pages.append([raw.strip() for raw in text.splitlines()
                              if raw.strip()])
        finally:
            doc.close()
        return self._filter_noise(pages)

    # ------------------------------------------------------------------
    _PAGE_NUM = re.compile(r"^(page\s+)?\d+(\s*(of|/)\s*\d+)?$", re.IGNORECASE)

    def _filter_noise(self, pages: List[List[str]]) -> List[str]:
        """Drop page numbers and repeated running headers/footers.

        A line that appears on 3+ pages (or on most pages of a short
        document) is a running header/footer, not questionnaire content.
        """
        from collections import Counter

        counts: Counter = Counter()
        for page in pages:
            for line in set(page):
                counts[line] += 1

        n_pages = len(pages)
        repeat_threshold = max(3, (n_pages // 2) + 1) if n_pages > 1 else 10**9

        lines: List[str] = []
        for page in pages:
            for line in page:
                if self._PAGE_NUM.match(line):
                    continue
                if n_pages > 1 and counts[line] >= repeat_threshold:
                    continue
                lines.append(line)
        return lines
