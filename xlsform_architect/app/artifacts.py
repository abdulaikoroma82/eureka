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
from .logic_flow import LogicFlowBuilder


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
            if q.is_structural:
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

        flow = LogicFlowBuilder().to_ascii(questionnaire)
        if flow:
            lines.append("## Skip-pattern flowchart")
            lines.append("")
            lines.append("Answer values are shown as their labels; the raw "
                         "expressions above stay authoritative. A graphical "
                         "version is in `logic_flow.dot` (open with any "
                         "Graphviz viewer) and in the app's Logic map tab.")
            lines.append("")
            lines.append("```text")
            lines.append(flow)
            lines.append("```")
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
    # Survey implementation package (Module D6)
    # ------------------------------------------------------------------
    #: Plain-words description of each answer type for the enumerator guide.
    _TYPE_WORDS = {
        "integer": "Record a whole number.",
        "decimal": "Record a number (decimals allowed).",
        "text": "Write the answer in words.",
        "date": "Record a date.",
        "time": "Record a time.",
        "datetime": "Record a date and time.",
        "select_one": "Select exactly ONE option.",
        "select_multiple": "Select ALL options that apply.",
        "rank": "Put the options in order.",
        "geopoint": "Capture the GPS location (stand outside if possible).",
        "image": "Take or attach a photo.",
        "audio": "Record audio.",
        "video": "Record video.",
        "file": "Attach a file.",
        "barcode": "Scan the code.",
        "note": "Read this to the respondent. No answer is recorded.",
    }

    def enumerator_guide_markdown(self, questionnaire: Questionnaire,
                                  duration=None) -> str:
        """Field-ready, question-by-question guide for enumerators."""
        from .logic_flow import LogicFlowBuilder

        flow = LogicFlowBuilder()
        s = questionnaire.settings
        lines = ["# Enumerator Reference Guide", "",
                 f"**Survey:** {s.form_title}  ",
                 f"**Version:** {s.version}  "]
        if duration is not None:
            lines.append(f"**Expected interview length:** about "
                         f"{duration.typical_minutes:.0f} minutes  ")
        lines += ["",
                  "Ask the questions in order. A question marked *(skip "
                  "rule)* only appears when its condition is met - the "
                  "device handles this automatically.", ""]

        current_section = object()
        number = 0
        for q in questionnaire.questions:
            if q.is_structural or q.is_calculate:
                continue
            if q.section != current_section:
                current_section = q.section
                if q.section:
                    lines += [f"## {q.section}", ""]
            number += 1
            required = " **(required)**" if q.required else ""
            lines.append(f"**{number}. {q.label or q.raw_label}**{required}")
            lines.append("")
            how = self._TYPE_WORDS.get(q.base_type,
                                       f"Record the answer ({q.base_type}).")
            lines.append(f"- *How to record:* {how}")
            if q.references_choices:
                cl = questionnaire.choice_lists.get(
                    self._question_list_name(q))
                if cl:
                    opts = "; ".join(c.label for c in cl.choices)
                    lines.append(f"- *Options:* {opts}")
            if q.relevant:
                lines.append(f"- *(skip rule)* Ask only when: "
                             f"{flow.describe_condition(q.relevant, questionnaire)}")
            if q.constraint_message:
                lines.append(f"- *Valid answers:* {q.constraint_message}")
            elif q.constraint:
                lines.append(f"- *Valid answers must satisfy:* "
                             f"`{q.constraint}`")
            if q.hint:
                lines.append(f"- *Note:* {q.hint}")
            if q.instruction:
                lines.append(f"- *Instruction:* {q.instruction}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def variable_specification_frame(self, questionnaire: Questionnaire) -> pd.DataFrame:
        """Data dictionary + provenance: one row per variable including the
        engine's logged assumptions, for analysts and data managers."""
        df = self.data_dictionary_frame(questionnaire)
        provenance = {q.name: " | ".join(q.assumptions)
                      for q in questionnaire.questions if not q.is_structural}
        df["assumptions"] = df["variable"].map(provenance).fillna("")
        return df

    def write_variable_specification(self, questionnaire: Questionnaire,
                                     path: Union[str, Path]) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.variable_specification_frame(questionnaire).to_excel(
            path, index=False, sheet_name="variable_specification")
        return path

    def collection_plan_markdown(self, questionnaire: Questionnaire,
                                 duration=None) -> str:
        """Data-collection plan skeleton derived from the form structure."""
        s = questionnaire.settings
        real = [q for q in questionnaire.questions
                if not q.is_structural and not q.is_calculate]
        lines = ["# Data Collection Plan", "",
                 f"**Survey:** {s.form_title}  ",
                 f"**Form id / version:** {s.form_id} / {s.version}  ", "",
                 "## Instrument overview", "",
                 f"- {len(real)} questions in "
                 f"{len({q.section for q in real if q.section}) or 1} "
                 f"section(s)"]
        if duration is not None:
            lines.append(f"- Estimated interview: "
                         f"~{duration.typical_minutes:.0f} minutes (range "
                         f"{duration.low_minutes:.0f}–"
                         f"{duration.high_minutes:.0f}); respondent-burden "
                         f"risk: {duration.burden_risk}")
            per_day = max(1, int((6 * 60) //
                                 max(1.0, duration.typical_minutes + 10)))
            lines.append(f"- Planning figure: ≈{per_day} interviews per "
                         f"enumerator per 6-hour field day (includes a "
                         f"10-minute buffer per interview for travel/consent)")
            if duration.per_section_minutes:
                lines += ["", "### Time by section", "",
                          "| Section | Est. minutes |", "| --- | --- |"]
                for section, minutes in duration.per_section_minutes.items():
                    lines.append(f"| {section} | {minutes:.1f} |")
        lines += ["", "## Device requirements", ""]
        needs = []
        types = {q.base_type for q in real}
        if "geopoint" in types:
            needs.append("GPS enabled (location capture)")
        if types & {"image", "video"}:
            needs.append("working camera (photo/video questions)")
        if types & {"audio", "video"}:
            needs.append("microphone (audio recording)")
        if "barcode" in types:
            needs.append("camera with barcode scanning")
        media_files = sorted({v.strip() for q in questionnaire.questions
                              for k, v in q.extra.items()
                              if k.startswith("media::") and v.strip()})
        if media_files:
            needs.append(f"{len(media_files)} media file(s) sideloaded: "
                         + ", ".join(media_files))
        lines += [f"- {n}" for n in needs] or ["- No special hardware needed."]

        languages = sorted({k.split("::", 1)[1]
                            for q in questionnaire.questions
                            for k in q.extra if k.startswith("label::")})
        lines += ["", "## Languages", ""]
        if languages:
            lines += [f"- Default plus: {', '.join(languages)}"]
        else:
            lines += ["- Single language (no translation columns)."]
        lines += ["", "## To complete manually", "",
                  "- Sampling design and target sample size",
                  "- Team structure, training dates and pilot plan",
                  "- Consent script and ethics approvals",
                  "- Data quality monitoring schedule"]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _question_list_name(q) -> str:
        parts = (q.xlsform_type or "").split()
        return parts[1] if len(parts) >= 2 else q.list_name

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
                                   if not q.is_structural]),
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
