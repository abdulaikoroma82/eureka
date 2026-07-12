"""Word (.docx) parser.

Purpose
-------
Extract text lines and tables from a Word questionnaire and hand them to the
:class:`QuestionnaireParser` for structuring.

Inputs
------
Path to a ``.docx`` file.

Outputs
-------
A raw :class:`~xlsform_studio.models.Questionnaire`.

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
        rows = self._table_cells(table)
        if not rows:
            return []
        grid = self._grid_lines(rows)
        if grid is not None:
            return grid

        lines: List[str] = []
        for cells in rows:
            cells = [c for c in cells if c]
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

    # ------------------------------------------------------------------
    def _table_cells(self, table) -> List[List[str]]:
        """Table content as rows of de-duplicated (merged-cell) text."""
        out: List[List[str]] = []
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            deduped: List[str] = []
            for c in cells:
                if not deduped or deduped[-1] != c:
                    deduped.append(c)
            out.append(deduped)
        return out

    def _grid_lines(self, rows: List[List[str]]) -> "List[str] | None":
        """Detect a matrix/grid question table and flatten it.

        A grid has a header row whose cells (after the first) are the shared
        answer scale, and body rows whose first cell is a sub-question while
        the remaining cells are empty or tick marks.  Each sub-question
        becomes its own select question with the shared options; identical
        option sets are merged into one list downstream.
        """
        if len(rows) < 3 or len(rows[0]) < 3:
            return None
        header = rows[0]
        options = [c for c in header[1:] if c]
        # Scale labels are short phrases; require at least two.
        if len(options) < 2 or any(len(o) > 40 for o in options):
            return None

        body = rows[1:]
        marks = {"", "x", "✓", "✔", "yes", "1", "•", "o"}
        for row in body:
            if not row or not row[0]:
                return None                      # sub-question cell required
            if any(c.lower() not in marks for c in row[1:] if c is not None):
                return None                      # data cells must be empty/ticks

        lines: List[str] = []
        for row in body:
            # "Q:: " is the parsers' internal forced-question sentinel: it
            # guarantees the text parser starts a new question here even
            # without a trailing question mark.
            lines.append(f"Q:: {row[0]}")
            for opt in options:
                lines.append(f"- {opt}")
        return lines
