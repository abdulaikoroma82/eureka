"""Output-package artefact generators.

Purpose
-------
Produce the supporting deliverables that accompany the XLSForm:

* **Data dictionary** (.xlsx + .csv) - every variable, type, list, constraint
  and calculation.
* **Assumption log** (.md) - every deterministic decision the engine made.
* **Logic map** (.md) - relevance / constraint / calculation relationships.
* **Version history** (.json, appended) - an audit trail across runs.

Inputs
------
A compiled :class:`~xlsform_architect.models.Questionnaire` and (for the
version history) run metadata.

Outputs
-------
Files written to the chosen output directory; helper methods also return the
in-memory content (bytes / str) for the Streamlit download buttons.

Example
-------
>>> from xlsform_architect.models import Questionnaire, Question
>>> qn = Questionnaire(questions=[Question(name="age", xlsform_type="integer", label="Age")])
>>> md = ArtifactBuilder().assumption_log_markdown(qn, ["note"])
>>> "Assumption Log" in md
True
"""

from __future__ import annotations

import datetime as _dt
import io
import json
from pathlib import Path
from typing import Dict, List, Union

import pandas as pd

from ..engine.knowledge_base import KnowledgeBase
from ..models import Questionnaire


class ArtifactBuilder:
    """Build the non-XLSForm deliverables."""

    def __init__(self, knowledge: KnowledgeBase | None = None) -> None:
        self.kb = knowledge or KnowledgeBase.load()

    # ------------------------------------------------------------------
    # Data dictionary
    # ------------------------------------------------------------------
    def data_dictionary_frame(self, questionnaire: Questionnaire) -> pd.DataFrame:
        rows: List[Dict[str, str]] = []
        for q in questionnaire.questions:
            if q.base_type in ("begin group", "end group"):
                continue
            list_name = ""
            choices = ""
            if q.references_choices:
                parts = q.xlsform_type.split()
                list_name = parts[1] if len(parts) >= 2 else q.list_name
                cl = questionnaire.choice_lists.get(list_name)
                if cl:
                    choices = " | ".join(f"{c.name}={c.label}" for c in cl.choices)
            rows.append({
                "variable": q.name,
                "label": q.label or q.raw_label,
                "type": q.xlsform_type,
                "choice_list": list_name,
                "choices": choices,
                "required": "yes" if q.required else "",
                "relevant": q.relevant,
                "constraint": q.constraint,
                "constraint_message": q.constraint_message,
                "calculation": q.calculation,
                "section": q.section,
            })
        return pd.DataFrame(rows)

    def write_data_dictionary(self, questionnaire: Questionnaire, path: Union[str, Path]) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        df = self.data_dictionary_frame(questionnaire)
        if path.suffix.lower() == ".csv":
            df.to_csv(path, index=False)
        else:
            df.to_excel(path, index=False, sheet_name="data_dictionary")
        return path

    # ------------------------------------------------------------------
    # Assumption log
    # ------------------------------------------------------------------
    def assumption_log_markdown(self, questionnaire: Questionnaire,
                                notes: List[str]) -> str:
        lines = ["# XLSForm Architect - Assumption Log", ""]
        lines.append(f"**Form:** {questionnaire.settings.form_title}  ")
        lines.append(f"**Generated:** {_dt.datetime.now():%Y-%m-%d %H:%M}  ")
        lines.append("")
        lines.append("Every decision below was made deterministically by the rule "
                     "engine. Review and adjust the source questionnaire or the "
                     "knowledge YAML files if any assumption is wrong.")
        lines.append("")
        if not notes:
            lines.append("_No assumptions were required._")
            return "\n".join(lines)
        lines.append("| # | Variable / Item | Assumption |")
        lines.append("| --- | --- | --- |")
        for i, note in enumerate(notes, start=1):
            var, _, msg = note.partition("] ")
            var = var.lstrip("[")
            lines.append(f"| {i} | {var} | {msg or note} |")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Logic map
    # ------------------------------------------------------------------
    def logic_map_markdown(self, questionnaire: Questionnaire) -> str:
        lines = ["# XLSForm Architect - Logic Map", ""]
        lines.append(f"**Form:** {questionnaire.settings.form_title}  ")
        lines.append("")

        rel = [q for q in questionnaire.questions if q.relevant]
        con = [q for q in questionnaire.questions if q.constraint]
        calc = [q for q in questionnaire.questions if q.calculation]

        lines.append("## Skip / relevance logic")
        lines.append("")
        if rel:
            lines.append("| Question | Shown when |")
            lines.append("| --- | --- |")
            for q in rel:
                lines.append(f"| `{q.name}` | `{q.relevant}` |")
        else:
            lines.append("_No conditional questions._")
        lines.append("")

        lines.append("## Constraints")
        lines.append("")
        if con:
            lines.append("| Question | Constraint | Message |")
            lines.append("| --- | --- | --- |")
            for q in con:
                lines.append(f"| `{q.name}` | `{q.constraint}` | {q.constraint_message} |")
        else:
            lines.append("_No constraints._")
        lines.append("")

        lines.append("## Calculations")
        lines.append("")
        if calc:
            lines.append("| Variable | Calculation |")
            lines.append("| --- | --- |")
            for q in calc:
                lines.append(f"| `{q.name}` | `{q.calculation}` |")
        else:
            lines.append("_No calculated fields._")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Version history (append-only audit trail)
    # ------------------------------------------------------------------
    def append_version_history(self, path: Union[str, Path],
                               questionnaire: Questionnaire,
                               source_name: str, is_valid: bool,
                               error_count: int, target: str = "") -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        history: List[Dict] = []
        if path.exists():
            try:
                history = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                history = []
        entry = {
            "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
            "form_title": questionnaire.settings.form_title,
            "form_id": questionnaire.settings.form_id,
            "version": questionnaire.settings.version,
            "source": source_name,
            "target": target,
            "category": questionnaire.category,
            "question_count": len([q for q in questionnaire.questions
                                   if q.base_type not in ("begin group", "end group")]),
            "valid": is_valid,
            "errors": error_count,
        }
        history.append(entry)
        path.write_text(json.dumps(history, indent=2), encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    @staticmethod
    def data_dictionary_bytes(df: pd.DataFrame) -> bytes:
        buffer = io.BytesIO()
        df.to_excel(buffer, index=False, sheet_name="data_dictionary")
        return buffer.getvalue()
