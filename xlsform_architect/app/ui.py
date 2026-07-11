"""Streamlit user interface (Module 10).

Purpose
-------
A local web UI to upload a questionnaire, pick a target platform
(KoboToolbox / SurveyCTO / ODK), generate a platform-tailored XLSForm and
download the full output package.

The chosen platform genuinely changes the output: the form is validated
against that platform's standards (from ``knowledge/platforms.yaml``) and the
workbook is written in that platform's column dialect (e.g. SurveyCTO's
``relevance`` header).

An optional AI-assist layer (DeepSeek) can be enabled in the sidebar for
translation, skip-logic resolution, type reclassification and a quality
review pass. It is off by default; the deterministic pipeline's behaviour is
completely unchanged unless a user explicitly enables it AND a DeepSeek API
key is configured.

Run
---
    streamlit run xlsform_architect/app/ui.py

The UI is a thin layer over :class:`Workflow`; all deterministic logic lives
in the rule engine, and all AI logic lives in the ``ai`` package - the
interface itself adds no intelligence of its own.
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

from xlsform_architect.ai.client import DeepSeekClient
from xlsform_architect.ai.config import AIConfig
from xlsform_architect.app.artifacts import ArtifactBuilder
from xlsform_architect.app.config import DEPLOYMENT_TARGETS, EXAMPLES_DIR
from xlsform_architect.app.workflow import STEP_LABELS, Workflow
from xlsform_architect.engine.knowledge_base import KnowledgeBase
from xlsform_architect.xlsform.choices_builder import ChoicesBuilder
from xlsform_architect.xlsform.survey_builder import SurveyBuilder

_UPLOAD_TYPES = ["docx", "xlsx", "xls", "pdf", "csv", "txt", "md", "json"]

_LEVEL_ICONS = {"error": "🔴", "warning": "🟠", "info": "🔵"}

#: Curated languages commonly used in M&E/survey work; users can add more
#: via the "Other language" field.
_COMMON_LANGUAGES = [
    ("French", "fr"), ("Spanish", "es"), ("Portuguese", "pt"),
    ("Arabic", "ar"), ("Swahili", "sw"), ("Hindi", "hi"),
    ("Bengali", "bn"), ("Amharic", "am"),
]

_AI_FEATURE_LABELS = {
    "classify": "Improve type detection (reclassify ambiguous questions)",
    "skip_logic": "Resolve skip-to-question jumps and unparseable conditions",
    "domain_constraints": "Suggest realistic value bounds for unconstrained questions",
    "cross_constraints": "Suggest cross-field constraints (e.g. end date after start date)",
    "translate": "Generate translations (only fills gaps you haven't already supplied)",
    "review": "AI quality review (semantics, naming clarity, respondent experience)",
    "explain_findings": "Explain validation findings in plain English",
    "group": "Suggest logical question sections (accept/reject after generating)",
    "rewrite": "Suggest clearer question wording (accept/reject after generating)",
    "order": "Suggest logical choice-list ordering (accept/reject after generating)",
    "naming": "Suggest clearer variable names (accept/reject after generating)",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _kb() -> KnowledgeBase:
    if "kb" not in st.session_state:
        st.session_state["kb"] = KnowledgeBase.load()
    return st.session_state["kb"]


def _platform_label(target: str) -> str:
    return _kb().platform(target).get("label", target.upper())


def _zip_outputs(folder: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in folder.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=path.relative_to(folder))
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
def _sidebar():
    with st.sidebar:
        st.markdown("### 🧩 XLSForm Architect")
        st.caption("Questionnaire → deployment-ready XLSForm. "
                   "Runs fully offline by default; AI assist is optional.")
        st.divider()

        st.markdown("**1 · Upload your questionnaire**")
        uploaded = st.file_uploader(
            "Questionnaire file", type=_UPLOAD_TYPES, label_visibility="collapsed",
            help="Word, Excel, PDF, CSV, plain text, or a structured JSON definition.")

        st.markdown("**2 · Where will you deploy it?**")
        targets = _kb().platform_names() or list(DEPLOYMENT_TARGETS)
        target = st.selectbox(
            "Target platform", targets, label_visibility="collapsed",
            format_func=_platform_label)
        profile = _kb().platform(target)
        if profile.get("dialect"):
            st.caption(f"✓ The workbook will be written in "
                       f"{_platform_label(target)}'s own column dialect.")
        else:
            st.caption(f"✓ Validated against {_platform_label(target)} standards.")

        with st.expander("3 · Form details (optional)"):
            form_title = st.text_input(
                "Form title", "",
                placeholder="e.g. Household Survey 2026")
            form_id = st.text_input(
                "Form id", "", placeholder="auto-generated from the title")
            version = st.text_input(
                "Version", "", placeholder="auto-generated timestamp")

        ai_config, ai_client = _ai_sidebar()

        st.divider()
        generate = st.button("⚙️  Generate XLSForm", type="primary",
                             use_container_width=True, disabled=uploaded is None)
        if uploaded is None:
            st.caption("Upload a questionnaire to enable generation.")

    return uploaded, target, form_title, form_id, version, ai_config, ai_client, generate


def _ai_sidebar():
    """AI-assist controls. Off by default; requires a DeepSeek API key."""
    with st.expander("4 · 🤖 AI assist (optional, uses DeepSeek)"):
        st.caption("Sends question labels to DeepSeek's API when enabled. "
                   "Off by default — the rest of this tool never leaves "
                   "your computer.")

        env_key = DeepSeekClient().api_key
        api_key = env_key
        if env_key:
            st.caption("✓ DEEPSEEK_API_KEY found in the environment.")
        else:
            api_key = st.text_input(
                "DeepSeek API key", type="password",
                help="Kept only for this browser session; never written to disk. "
                     "Set the DEEPSEEK_API_KEY environment variable instead to "
                     "avoid entering it here.")

        enabled = st.checkbox("Enable AI assist", value=False,
                              disabled=not api_key)
        if not api_key:
            st.caption("Enter an API key above to enable AI features.")
            return AIConfig.disabled(), None

        features = []
        if enabled:
            for key, label in _AI_FEATURE_LABELS.items():
                if st.checkbox(label, value=True, key=f"ai_feat_{key}"):
                    features.append(key)

        survey_context = ""
        if enabled and ({"domain_constraints", "review"} & set(features)):
            survey_context = st.text_input(
                "What is this survey about? (optional)",
                placeholder="e.g. child nutrition survey in rural districts",
                help="Grounds the AI's value-bound and review suggestions in "
                     "your survey's actual domain — a 'temperature' means "
                     "something different in a health survey than a weather "
                     "one.")

        languages = []
        if enabled and "translate" in features:
            chosen = st.multiselect(
                "Languages to translate into",
                options=[f"{name} ({code})" for name, code in _COMMON_LANGUAGES],
                default=[])
            languages = [(n, c) for n, c in _COMMON_LANGUAGES
                        if f"{n} ({c})" in chosen]
            other = st.text_input("Other language (Name:code)", "",
                                  placeholder="e.g. German:de")
            name, _, code = other.partition(":")
            if name.strip() and code.strip():
                languages.append((name.strip(), code.strip()))
            if not languages:
                st.caption("Pick at least one language, or translation will be skipped.")

        config = AIConfig(enabled=enabled, features=features,
                          translate_languages=languages,
                          survey_context=survey_context)
        client = DeepSeekClient(api_key=api_key) if enabled else None
        return config, client


# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------
def _render_landing() -> None:
    st.title("🧩 XLSForm Architect")
    st.markdown(
        "Turn **any questionnaire** — Word, Excel, PDF, CSV or plain text — "
        "into a validated, deployment-ready **XLSForm** for KoboToolbox, "
        "SurveyCTO, ODK, Ona or CommCare.")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("#### 📄 → 📋 Parse")
        st.caption("Sections, questions, answer options and skip rules are "
                   "extracted automatically from your document.")
    with c2:
        st.markdown("#### ⚙️ Compile")
        st.caption("Deterministic rules assign field types, clean variable "
                   "names, skip logic, validation constraints and calculations.")
    with c3:
        st.markdown("#### ✅ Validate")
        st.caption("Checked against the XLSForm spec, your chosen platform's "
                   "standards, and the actual ODK/Kobo engine (pyxform).")

    st.divider()
    st.markdown("##### Try it with a sample questionnaire")
    samples = sorted(EXAMPLES_DIR.glob("*")) if EXAMPLES_DIR.exists() else []
    if samples:
        cols = st.columns(min(len(samples), 4))
        for col, sample in zip(cols, samples):
            with col:
                st.download_button(
                    f"📥 {sample.name}", data=sample.read_bytes(),
                    file_name=sample.name, use_container_width=True,
                    key=f"sample_{sample.name}")
        st.caption("Download a sample, then upload it in the sidebar to see "
                   "the full pipeline in action.")

    with st.expander("✍️ Tips for writing questionnaires the parser loves"):
        st.markdown(
            """
            - **End questions with a question mark** — `What is your age?`
            - **List answer options on their own lines** directly under the question:

              &nbsp;&nbsp;`What is your gender?`  \\
              &nbsp;&nbsp;`Male`  \\
              &nbsp;&nbsp;`Female`
            - **Write skip rules in plain English** — `If yes, record the date.`
              Compound and rich rules work too: `if yes and age over 18`,
              `unless married`, `if age between 18 and 65`, and numbered
              references like `If question 4 is married`.
            - **Number your questions** (`1.`, `Q2:`, `3)`) — numbering is
              captured, so skip rules can reference questions by number.
            - **Coded answer options are kept**: `1 = Single` stores code `1`
              with label "Single".
            - **Mark required questions** with a trailing `*` or `(required)`.
            - **Use CAPITALISED headings** (or lines starting with "Section")
              to group questions into sections.
            - **Rosters**: a heading like `FOR EACH HOUSEHOLD MEMBER` turns the
              questions under it into a repeat group.
            - **Rating grids** (a Word table with one row per item and the
              scale across the top) become one question per row, sharing a
              single choice list.
            - An **"Other (specify)"** option automatically gets a text
              follow-up shown only when Other is selected.
            - Every automatic decision is listed in the **assumption log**, so
              nothing happens silently.
            """)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
def _render_result(result, target: str) -> None:
    report = result.report
    qn = result.questionnaire
    label = _platform_label(target)

    real = [q for q in qn.questions
            if not q.is_structural]

    if not real:
        st.error("No questions could be extracted from this file. "
                 "Check that it contains questionnaire text (see the writing "
                 "tips on the home page), or try the CSV/JSON format for an "
                 "exact, no-guessing import.")
        return

    # --- headline ----------------------------------------------------------
    if report.is_valid:
        st.success(f"**{qn.settings.form_title}** compiled and validated — "
                   f"ready to upload to **{label}**.", icon="✅")
    else:
        st.error(f"**{qn.settings.form_title}** was generated, but has "
                 f"**{len(report.errors)} blocking issue(s)** for {label}. "
                 f"Review the findings below before deploying.", icon="⚠️")

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Questions", len(real))
    m2.metric("Choice lists", len(qn.choice_lists))
    m3.metric("Skip rules", len([q for q in real if q.relevant]))
    m4.metric("Errors", len(report.errors))
    m5.metric("Warnings", len(report.warnings))

    # --- compatibility -----------------------------------------------------
    st.markdown("##### Platform compatibility")
    cols = st.columns(len(report.compatibility) or 1)
    for col, (platform, ok) in zip(cols, report.compatibility.items()):
        icon = "✅" if ok else "❌"
        marker = " ← your target" if platform == target else ""
        col.markdown(f"{icon} **{_platform_label(platform)}**{marker}")
    if report.deep_ran:
        st.caption("Deep check: this form was converted by pyxform — the same "
                   "engine ODK and KoboToolbox run — as part of validation.")
    if result.ai_ran:
        st.caption("🤖 AI assist ran on this form — review any AI-suggested "
                   "changes (marked in the assumption log and findings below) "
                   "before deploying.")

    _render_ai_suggestions(result, target)

    # --- downloads ---------------------------------------------------------
    st.markdown("##### Downloads")
    fid = qn.settings.form_id or "form"
    ver = qn.settings.version or "1"
    d1, d2 = st.columns(2)
    d1.download_button(
        f"⬇️  XLSForm for {label} (.xlsx)", data=result.xlsform_bytes,
        file_name=f"{fid}_{target}_v{ver}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True, type="primary")
    folder = result.outputs.get("folder")
    if folder:
        d2.download_button(
            "⬇️  Full package (.zip)", data=_zip_outputs(folder),
            file_name=f"{fid}_{target}_v{ver}_package.zip",
            mime="application/zip", use_container_width=True)
        st.caption("The package adds the data dictionary, QA report (PDF), "
                   "assumption log, logic map and version history.")

    # --- detail tabs ---------------------------------------------------------
    tabs = st.tabs(["📋 Form preview", "🔤 Choices",
                    f"🧪 Findings ({len(report.findings)})",
                    f"🎯 {label} guide", "🧠 Assumptions", "🗺 Logic map"])

    with tabs[0]:
        df = pd.DataFrame(SurveyBuilder().build(qn))
        st.dataframe(df, use_container_width=True, hide_index=True)

    with tabs[1]:
        ch = pd.DataFrame(ChoicesBuilder().build(qn))
        if len(ch):
            st.dataframe(ch, use_container_width=True, hide_index=True)
        else:
            st.caption("This form has no choice lists.")

    with tabs[2]:
        if not report.findings:
            st.success("No issues found — a completely clean run.")
        for f in report.sorted_findings():
            icon = "🤖" if f.category == "ai_review" else _LEVEL_ICONS.get(f.level, "🔵")
            loc = f" — `{f.location}`" if f.location else ""
            st.markdown(f"{icon} **{f.category}**{loc}: {f.message}")
            if f.explanation:
                st.caption(f"💬 {f.explanation}")

    with tabs[3]:
        _render_platform_guide(target)

    with tabs[4]:
        st.markdown(ArtifactBuilder(_kb()).assumption_log_markdown(
            qn, result.assumptions))

    with tabs[5]:
        st.markdown(ArtifactBuilder(_kb()).logic_map_markdown(qn))


def _render_ai_suggestions(result, target: str) -> None:
    """Accept/reject panel for advisory AI suggestions.

    Nothing here is applied until the user ticks a suggestion and clicks
    apply — the form the download buttons serve is always the current,
    human-approved state.
    """
    pending = [s for s in result.ai_suggestions if not s.applied]
    if not pending:
        return

    kind_names = {"grouping": "Section grouping", "rewording": "Wording",
                  "split": "Split question", "choice_order": "Choice order",
                  "naming": "Variable name"}
    with st.expander(f"🤖 AI suggestions ({len(pending)}) — review and "
                     f"accept to apply", expanded=True):
        st.caption("Advisory only: none of these changed your form. Tick "
                   "the ones you want, then apply — the XLSForm is rebuilt "
                   "and re-validated with your accepted changes.")
        accepted_keys = []
        for i, sug in enumerate(pending):
            kind = kind_names.get(sug.kind, sug.kind)
            where = f" — `{sug.target}`" if sug.target else ""
            st.markdown(f"**{kind}**{where}")
            c1, c2 = st.columns(2)
            c1.markdown(f"*Current:*\n\n{sug.original}")
            c2.markdown(f"*Suggested:*\n\n{sug.suggested}")
            caption_bits = [b for b in (
                sug.reason,
                f"confidence: {sug.confidence}" if sug.confidence else "")
                if b]
            if caption_bits:
                st.caption("💬 " + " · ".join(caption_bits))
            if sug.appliable:
                if st.checkbox("Accept", key=f"ai_sug_accept_{i}"):
                    accepted_keys.append(i)
            else:
                st.caption("↩️ Apply this one by editing the source "
                           "document (splitting a question changes the "
                           "data model, so the tool won't do it for you).")
            st.divider()

        if st.button(f"✅ Apply {len(accepted_keys)} accepted suggestion(s) "
                     f"and rebuild", disabled=not accepted_keys,
                     use_container_width=True):
            accepted = [pending[i] for i in accepted_keys]
            Workflow(knowledge=_kb()).apply_ai_suggestions(result, accepted)
            st.session_state["last_result"] = result
            st.rerun()


def _render_platform_guide(target: str) -> None:
    profile = _kb().platform(target)
    label = profile.get("label", target.upper())
    st.markdown(f"**Deploying to {label}** — "
                f"[official documentation]({profile.get('docs', '#')})")
    dialect = profile.get("dialect") or {}
    if dialect:
        renames = ", ".join(f"`{a}` → `{b}`" for a, b in dialect.items())
        st.info(f"This XLSForm was written in {label}'s column dialect: {renames}.")
    for tip in profile.get("tips", []):
        st.markdown(f"- {tip}")
    meta = profile.get("metadata_types", [])
    if meta:
        st.caption("Commonly added metadata fields on this platform: "
                   + ", ".join(f"`{m}`" for m in meta))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="XLSForm Architect", page_icon="🧩",
                       layout="wide")

    (uploaded, target, form_title, form_id, version,
     ai_config, ai_client, generate) = _sidebar()

    if uploaded is None:
        _render_landing()
        return

    if not generate and "last_result" not in st.session_state:
        st.title("🧩 XLSForm Architect")
        st.info(f"Loaded **{uploaded.name}** — choose your platform in the "
                f"sidebar and click **Generate XLSForm**.", icon="📄")
        return

    if generate:
        # Persist the upload to a temp file so parsers can read it.
        suffix = Path(uploaded.name).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded.getbuffer())
            tmp_path = Path(tmp.name)

        st.title("🧩 XLSForm Architect")
        placeholders = {lbl: st.empty() for lbl in STEP_LABELS}
        for lbl in STEP_LABELS:
            placeholders[lbl].markdown(f"◻️ {lbl}")

        def progress(step: str, status: str) -> None:
            icon = "⏳" if status == "running" else "✅"
            placeholders[step].markdown(f"{icon} {step}")

        try:
            result = Workflow(knowledge=_kb(), ai_client=ai_client).run_from_file(
                tmp_path,
                form_title=form_title or None,
                form_id=form_id or None,
                version=version or None,
                target=target,
                source_name=uploaded.name,
                ai_config=ai_config,
                progress=progress,
            )
        except Exception as exc:  # pragma: no cover - surfaced to the user
            st.error(f"Could not process **{uploaded.name}**: {exc}")
            return
        finally:
            tmp_path.unlink(missing_ok=True)

        for lbl in STEP_LABELS:      # collapse the step list once done
            placeholders[lbl].empty()
        st.session_state["last_result"] = result
        st.session_state["last_target"] = target

    result = st.session_state.get("last_result")
    if result is not None:
        _render_result(result, st.session_state.get("last_target", target))


if __name__ == "__main__":  # pragma: no cover
    main()
