"""Excel / CSV parser (Module 1 / Iteration 3).

Purpose
-------
Read a tabular questionnaire (one row per question) from ``.xlsx`` / ``.xls``
/ ``.csv`` and build a :class:`~xlsform_studio.models.Questionnaire`.

Two shapes are supported and auto-detected:

1. **Already an XLSForm** - a workbook containing ``survey`` (and optionally
   ``choices`` / ``settings``) sheets is loaded directly, preserving existing
   types, names and choice lists.
2. **A design grid** - a single table whose columns describe questions.
   Recognised (case-insensitive) column aliases::

       question / label / text        -> question label
       type / question_type           -> xlsform type (optional)
       choices / options / responses  -> options ("Yes|No" or "Yes,No")
       name / variable                -> variable name (optional)
       hint                           -> hint
       required                       -> required flag
       relevant / skip / logic        -> logic
       section / group                -> section
       constraint / calculation       -> passthrough

Inputs
------
Path to a spreadsheet / CSV.

Outputs
-------
A :class:`Questionnaire` (raw for design grids; already-structured for
XLSForm workbooks).

Example
-------
>>> qn = ExcelParser().parse("design.xlsx")   # doctest: +SKIP
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Union

import pandas as pd

from ..models import Choice, ChoiceList, FormSettings, Question, Questionnaire

_SPLIT_CHARS = ["|", ";", ",", "/"]

_COLUMN_ALIASES: Dict[str, List[str]] = {
    "label": ["question", "label", "text", "question text", "item"],
    "type": ["type", "question_type", "question type", "xlsform_type"],
    "choices": ["choices", "options", "responses", "response options", "answers"],
    "name": ["name", "variable", "variable name", "var", "field"],
    "hint": ["hint", "instruction", "instructions", "help"],
    "required": ["required", "mandatory"],
    "logic": ["relevant", "skip", "logic", "skip pattern", "condition"],
    "section": ["section", "group", "module"],
    "constraint": ["constraint", "validation"],
    "calculation": ["calculation", "calculate", "formula"],
    "list_name": ["list_name", "list name", "choice list"],
    "choice_filter": ["choice_filter", "choice filter", "cascade"],
    "repeat": ["repeat", "repeat_group", "repeat group", "roster"],
}


class ExcelParser:
    """Parse tabular questionnaires and existing XLSForms."""

    def parse(self, path: Union[str, Path]) -> Questionnaire:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Spreadsheet not found: {path}")

        if path.suffix.lower() == ".csv":
            df = pd.read_csv(path, dtype=str, keep_default_na=False)
            return self._from_design_grid(df)

        sheets = pd.read_excel(path, sheet_name=None, dtype=str)
        sheets = {name.lower().strip(): df.fillna("") for name, df in sheets.items()}

        if "survey" in sheets:
            return self._from_xlsform(sheets)
        # Otherwise treat the first sheet as a design grid.
        first = next(iter(sheets.values()))
        return self._from_design_grid(first)

    # ------------------------------------------------------------------
    # Design grid (one row per question).
    # ------------------------------------------------------------------
    def _from_design_grid(self, df: pd.DataFrame) -> Questionnaire:
        df = df.fillna("")
        colmap = self._map_columns(list(df.columns))
        qn = Questionnaire()

        for _, row in df.iterrows():
            label = self._val(row, colmap, "label")
            if not label:
                continue
            q = Question(raw_label=label)
            q.xlsform_type = self._val(row, colmap, "type")
            q.name = self._val(row, colmap, "name")
            q.hint = self._val(row, colmap, "hint")
            q.section = self._val(row, colmap, "section")
            q.logic = self._val(row, colmap, "logic")
            q.constraint = self._val(row, colmap, "constraint")
            q.calculation = self._val(row, colmap, "calculation")
            q.list_name = self._val(row, colmap, "list_name")
            q.choice_filter = self._val(row, colmap, "choice_filter")
            required = self._val(row, colmap, "required").strip().lower()
            q.required = required in ("1", "yes", "true", "y", "required")
            repeat = self._val(row, colmap, "repeat").strip().lower()
            if repeat in ("1", "yes", "true", "y", "repeat"):
                q.section_type = "repeat"
            choices_raw = self._val(row, colmap, "choices")
            if choices_raw:
                q.raw_choices = self._split_choices(choices_raw)
            # Passthrough columns (translations, media), e.g. "label::French (fr)".
            for col in df.columns:
                if "::" in str(col):
                    value = str(row.get(col, "")).strip()
                    if value:
                        q.extra[str(col)] = value
            qn.questions.append(q)
        return qn

    # ------------------------------------------------------------------
    # Existing XLSForm workbook.
    # ------------------------------------------------------------------
    #: survey-sheet headers consumed into first-class Question fields;
    #: anything else is preserved as a passthrough column.
    _KNOWN_SURVEY = {"type", "name", "label", "hint", "required", "relevant",
                     "relevance", "constraint", "constraint_message",
                     "constraint message", "calculation", "choice_filter",
                     "appearance", "default"}

    def _from_xlsform(self, sheets: Dict[str, pd.DataFrame]) -> Questionnaire:
        qn = Questionnaire()
        survey = sheets["survey"].fillna("")

        for _, row in survey.iterrows():
            qtype = str(row.get("type", "")).strip()
            if not qtype:
                continue
            # Accept SurveyCTO's dialect headers on the way in too.
            relevant = (str(row.get("relevant", "")).strip()
                        or str(row.get("relevance", "")).strip())
            cmessage = (str(row.get("constraint_message", "")).strip()
                        or str(row.get("constraint message", "")).strip())
            q = Question(
                raw_label=str(row.get("label", "")).strip(),
                name=str(row.get("name", "")).strip(),
                xlsform_type=qtype,
                label=str(row.get("label", "")).strip(),
                hint=str(row.get("hint", "")).strip(),
                relevant=relevant,
                constraint=str(row.get("constraint", "")).strip(),
                constraint_message=cmessage,
                calculation=str(row.get("calculation", "")).strip(),
                choice_filter=str(row.get("choice_filter", "")).strip(),
                appearance=str(row.get("appearance", "")).strip(),
                default=str(row.get("default", "")).strip(),
            )
            q.required = str(row.get("required", "")).strip().lower() in ("yes", "true", "1")
            if q.references_choices:
                parts = qtype.split()
                if len(parts) >= 2:
                    q.list_name = parts[1]
            # Preserve unknown columns (translations, media, parameters...).
            for col in survey.columns:
                key = str(col).strip()
                if key.lower() not in self._KNOWN_SURVEY:
                    value = str(row.get(col, "")).strip()
                    if value:
                        q.extra[key] = value
            qn.questions.append(q)

        # Choices sheet (extra columns such as label::lang / filters preserved).
        if "choices" in sheets:
            ch = sheets["choices"].fillna("")
            for _, row in ch.iterrows():
                list_name = str(row.get("list_name", "")).strip()
                name = str(row.get("name", "")).strip()
                if not list_name or not name:
                    continue
                extra = {}
                for col in ch.columns:
                    key = str(col).strip()
                    if key.lower() not in ("list_name", "name", "label"):
                        value = str(row.get(col, "")).strip()
                        if value:
                            extra[key] = value
                cl = qn.get_or_create_list(list_name)
                cl.choices.append(Choice(name=name,
                                         label=str(row.get("label", name)).strip(),
                                         extra=extra))

        # Settings sheet.
        if "settings" in sheets:
            st = sheets["settings"].fillna("")
            if len(st):
                row = st.iloc[0]
                qn.settings = FormSettings(
                    form_title=str(row.get("form_title", "Untitled Form")).strip() or "Untitled Form",
                    form_id=str(row.get("form_id", "")).strip(),
                    version=str(row.get("version", "")).strip(),
                )
        return qn

    # ------------------------------------------------------------------
    def _map_columns(self, columns: List[str]) -> Dict[str, str]:
        lower = {c.lower().strip(): c for c in columns}
        mapping: Dict[str, str] = {}
        for canonical, aliases in _COLUMN_ALIASES.items():
            for alias in aliases:
                if alias in lower:
                    mapping[canonical] = lower[alias]
                    break
        return mapping

    def _val(self, row, colmap: Dict[str, str], key: str) -> str:
        col = colmap.get(key)
        if not col:
            return ""
        return str(row.get(col, "")).strip()

    @staticmethod
    def _split_choices(raw: str) -> List[str]:
        for ch in _SPLIT_CHARS:
            if ch in raw:
                return [p.strip() for p in raw.split(ch) if p.strip()]
        return [raw.strip()] if raw.strip() else []
