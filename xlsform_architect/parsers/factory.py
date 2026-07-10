"""Parser factory / dispatcher (Module 1).

Purpose
-------
Choose the right parser for a given input file (by extension) and return a
raw :class:`~xlsform_architect.models.Questionnaire`.  Also handles the JSON
input format used by Iteration 1.

Inputs
------
Path to any supported file (``.json .csv .xlsx .xls .docx .pdf``).

Outputs
-------
A raw :class:`Questionnaire`.

Example
-------
>>> qn = parse_file("questionnaire.docx")   # doctest: +SKIP
>>> qn = parse_file("form.json")            # doctest: +SKIP
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Union

from ..models import Questionnaire
from .docx_parser import DocxParser
from .excel_parser import ExcelParser
from .pdf_parser import PdfParser


def parse_file(path: Union[str, Path]) -> Questionnaire:
    """Dispatch *path* to the appropriate parser based on its extension."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".json":
        with path.open("r", encoding="utf-8") as fh:
            return Questionnaire.from_dict(json.load(fh))
    if suffix in (".xlsx", ".xls", ".csv"):
        return ExcelParser().parse(path)
    if suffix == ".docx":
        return DocxParser().parse(path)
    if suffix == ".pdf":
        return PdfParser().parse(path)
    if suffix in (".txt", ".md"):
        from .questionnaire_parser import QuestionnaireParser
        return QuestionnaireParser().parse_text(path.read_text(encoding="utf-8"))
    raise ValueError(f"Unsupported input format: {suffix}. "
                     "Supported: .json .csv .xlsx .xls .docx .pdf .txt")
