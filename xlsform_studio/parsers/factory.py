"""Parser factory / dispatcher.

Purpose
-------
Choose the right parser for a given input file (by extension) and return a
raw :class:`~xlsform_studio.models.Questionnaire`.  Also handles the
structured JSON input format.

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

from ..app.config import MAX_INPUT_BYTES, SUPPORTED_INPUT_EXTENSIONS
from ..models import Questionnaire
from .docx_parser import DocxParser
from .excel_parser import ExcelParser
from .pdf_parser import PdfParser


def parse_file(path: Union[str, Path]) -> Questionnaire:
    """Dispatch *path* to the appropriate parser based on its extension."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    # Guard memory before any parser reads the whole file into RAM.
    size = path.stat().st_size
    if size > MAX_INPUT_BYTES:
        raise ValueError(
            f"Input file is {size / 1_048_576:.1f} MB, above the "
            f"{MAX_INPUT_BYTES // 1_048_576} MB limit "
            f"(set XLSFS_MAX_INPUT_MB to change it).")

    suffix = path.suffix.lower()
    if suffix == ".json":
        with path.open("r", encoding="utf-8") as fh:
            return Questionnaire.from_dict(json.load(fh))
    if suffix in (".xlsx", ".csv"):
        return ExcelParser().parse(path)
    if suffix == ".docx":
        return DocxParser().parse(path)
    if suffix == ".pdf":
        return PdfParser().parse(path)
    if suffix in (".txt", ".md"):
        from .questionnaire_parser import QuestionnaireParser
        return QuestionnaireParser().parse_text(path.read_text(encoding="utf-8"))
    raise ValueError(
        f"Unsupported input format: {suffix or '(none)'}. Supported: "
        f"{' '.join(SUPPORTED_INPUT_EXTENSIONS)}.")
