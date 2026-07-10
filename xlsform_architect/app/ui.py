"""Streamlit user interface (Module 10 / Iteration 7).

Purpose
-------
A local web UI to upload a questionnaire, pick a survey category and
deployment target, generate the XLSForm and download the full output
package.

Run
---
    streamlit run xlsform_architect/app/ui.py

The UI is a thin layer over :class:`Workflow`; all logic lives in the
deterministic engine, so the interface adds no intelligence of its own.
"""

from __future__ import annotations

import io
import sys
import tempfile
import zipfile
from pathlib import Path

# ``streamlit run`` executes this file as a top-level script (no package
# context), which breaks relative imports.  Make the project importable so we
# can use absolute imports either way.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    raise SystemExit("Streamlit is not installed. Run: pip install streamlit")

import pandas as pd

from xlsform_architect.app.artifacts import ArtifactBuilder
from xlsform_architect.app.config import DEPLOYMENT_TARGETS
from xlsform_architect.app.workflow import STEP_LABELS, Workflow
from xlsform_architect.xlsform.choices_builder import ChoicesBuilder
from xlsform_architect.xlsform.survey_builder import SurveyBuilder


def _zip_outputs(folder: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in folder.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=path.relative_to(folder))
    return buffer.getvalue()


def main() -> None:
    st.set_page_config(page_title="XLSForm Architect", page_icon="🧩", layout="wide")
    st.title("🧩 XLSForm Architect")
    st.caption("Deterministic, rule-based questionnaire → XLSForm compiler "
               "(KoboToolbox · SurveyCTO · ODK). No AI services required.")

    with st.sidebar:
        st.header("1. Upload questionnaire")
        uploaded = st.file_uploader(
            "Questionnaire file",
            type=["json", "csv", "xlsx", "xls", "docx", "pdf"],
            help="DOCX, XLSX, PDF, CSV or a structured JSON form definition.")

        st.header("2. Deployment target")
        target = st.selectbox("Target platform", DEPLOYMENT_TARGETS,
                              format_func=lambda t: t.upper())

        st.header("3. Form details (optional)")
        form_title = st.text_input("Form title", "")
        form_id = st.text_input("Form id", "")
        version = st.text_input("Version", "")

        generate = st.button("⚙️ Generate XLSForm", type="primary",
                             use_container_width=True, disabled=uploaded is None)

    if uploaded is None:
        st.info("Upload a questionnaire in the sidebar to begin.")
        _render_help()
        return

    if not generate:
        st.success(f"Loaded **{uploaded.name}**. Configure options and click "
                   f"**Generate XLSForm**.")
        return

    # Persist the upload to a temp file so parsers can read it.
    suffix = Path(uploaded.name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded.getbuffer())
        tmp_path = Path(tmp.name)

    # Live processing steps.
    st.subheader("Processing")
    placeholders = {label: st.empty() for label in STEP_LABELS}
    for label in STEP_LABELS:
        placeholders[label].markdown(f"⬜ {label}")

    def progress(step: str, status: str) -> None:
        icon = "⏳" if status == "running" else "✅"
        placeholders[step].markdown(f"{icon} {step}")

    workflow = Workflow()
    try:
        result = workflow.run_from_file(
            tmp_path,
            form_title=form_title or None,
            form_id=form_id or None,
            version=version or None,
            progress=progress,
        )
    except Exception as exc:  # pragma: no cover - surfaced to the user
        st.error(f"Failed to process questionnaire: {exc}")
        return
    finally:
        tmp_path.unlink(missing_ok=True)

    _render_result(result, target)


def _render_result(result, target: str) -> None:
    report = result.report
    qn = result.questionnaire

    st.subheader("Result")
    if report.is_valid:
        st.success(f"XLSForm generated and validated — ready for "
                   f"**{target.upper()}** deployment.")
    else:
        st.warning("XLSForm generated with validation errors — review below "
                   "before deploying.")

    c1, c2, c3, c4 = st.columns(4)
    real = [q for q in qn.questions if q.base_type not in ("begin group", "end group")]
    c1.metric("Questions", len(real))
    c2.metric("Choice lists", len(qn.choice_lists))
    c3.metric("Errors", len(report.errors))
    c4.metric("Warnings", len(report.warnings))

    # Downloads.
    st.subheader("Downloads")
    folder = result.outputs.get("folder")
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ XLSForm (.xlsx)", data=result.xlsform_bytes,
                       file_name=f"{qn.settings.form_id}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)
    if folder:
        d2.download_button("⬇️ Full package (.zip)", data=_zip_outputs(folder),
                           file_name=f"{qn.settings.form_id}_package.zip",
                           mime="application/zip", use_container_width=True)

    # Compatibility.
    st.subheader("Deployment compatibility")
    cols = st.columns(len(report.compatibility))
    for col, (platform, ok) in zip(cols, report.compatibility.items()):
        col.markdown(f"**{platform.upper()}**  \n{'✅ Compatible' if ok else '❌ Issues'}")

    # Tabs with detail.
    tab_survey, tab_choices, tab_report, tab_assume, tab_logic = st.tabs(
        ["Survey", "Choices", "Validation", "Assumptions", "Logic map"])

    with tab_survey:
        st.dataframe(pd.DataFrame(SurveyBuilder().build(qn)), use_container_width=True)

    with tab_choices:
        st.dataframe(pd.DataFrame(ChoicesBuilder().build(qn)), use_container_width=True)

    with tab_report:
        for f in report.sorted_findings():
            loc = f" [`{f.location}`]" if f.location else ""
            {"error": st.error, "warning": st.warning}.get(f.level, st.info)(
                f"**{f.category}**{loc}: {f.message}")
        if report.is_valid and not report.findings:
            st.success("No issues found.")

    with tab_assume:
        st.markdown(ArtifactBuilder().assumption_log_markdown(qn, result.assumptions))

    with tab_logic:
        st.markdown(ArtifactBuilder().logic_map_markdown(qn))


def _render_help() -> None:
    st.markdown(
        """
        ### How it works
        1. **Upload** a questionnaire (Word, Excel, PDF, CSV, or structured JSON).
        2. The **parser** extracts sections, questions and options.
        3. The **rule engine** assigns XLSForm types, variable names, skip
           logic, constraints and calculations — all deterministically.
        4. The **validator** checks structure, logic and deployment
           compatibility with Kobo, SurveyCTO and ODK.
        5. **Download** the XLSForm plus a data dictionary, QA report,
           assumption log and logic map.

        No Claude, ChatGPT or paid AI service is involved — the intelligence
        comes entirely from rules, templates and validators you can edit in
        the `knowledge/` YAML files.
        """)


if __name__ == "__main__":  # pragma: no cover
    main()
