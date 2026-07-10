"""Word (.docx) parser (Module 1 / Iteration 4).

Purpose
-------
Extract text lines and tables from a Word questionnaire and hand them to the
:class:`QuestionnaireParser` for structuring.

Inputs
------
Path to a ``.docx`` file.

Outputs
-------
A raw :class:`~xlsform_architect.models.Questionnaire`.

Notes
-----
* Paragraph text is read in document order.
* Tables are flattened row-by-row; a two-column table is interpreted as
  question/answer or option grids.

Example
-------
>>> qn = DocxParser().parse("survey.docx")   # doctest: +SKIP
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Union

from ..models import Questionnaire
from .questionnaire_parser import QuestionnaireParser


class DocxParser:
    """Parse Microsoft Word questionnaires."""

    def __init__(self) -> None:
        self.text_parser = QuestionnaireParser()

    def parse(self, path: Union[str, Path]) -> Questionnaire:
        lines = self.extract_lines(path)
        return self.text_parser.parse_lines(lines)

    # ------------------------------------------------------------------
    def extract_lines(self, path: Union[str, Path]) -> List[str]:
        try:
            import docx  # python-docx
        except ImportError as exc:  # pragma: no cover
            raise ImportError("python-docx is required to parse .docx files "
                              "(pip install python-docx).") from exc

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"DOCX file not found: {path}")

        document = docx.Document(str(path))
        lines: List[str] = []

        # Iterate body elements in order so paragraphs and tables interleave
        # the way they appear in the document.
        for block in self._iter_block_items(document):
            if block[0] == "paragraph":
                text = block[1].strip()
                if text:
                    lines.append(text)
            else:  # table
                lines.extend(self._table_lines(block[1]))
        return lines

    # ------------------------------------------------------------------
    def _iter_block_items(self, document):
        """Yield ('paragraph', text) / ('table', table) in document order."""
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        parent_elm = document.element.body
        for child in parent_elm.iterchildren():
            if child.tag.endswith("}p"):
                yield ("paragraph", Paragraph(child, document).text)
            elif child.tag.endswith("}tbl"):
                yield ("table", Table(child, document))

    def _table_lines(self, table) -> List[str]:
        lines: List[str] = []
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            # De-duplicate merged cells that repeat text.
            deduped: List[str] = []
            for c in cells:
                if not deduped or deduped[-1] != c:
                    deduped.append(c)
            cells = [c for c in deduped if c]
            if not cells:
                continue
            if len(cells) == 1:
                lines.append(cells[0])
            else:
                # First cell as question/label; remaining cells as options.
                lines.append(cells[0])
                for opt in cells[1:]:
                    lines.append(f"- {opt}")
        return lines
