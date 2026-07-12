"""Tests for the final roadmap items: reverse engineering round-trip (D1),
the printable survey instrument, indicator mapping (A8), the expanded
expert-panel review brief (A1/A2/A14), and Mermaid export (D2 extension)."""

from __future__ import annotations

from xlsform_studio.ai.client import DeepSeekClient
from xlsform_studio.ai.config import AIConfig
from xlsform_studio.ai.indicators import AIIndicatorMapper
from xlsform_studio.ai.quality_reviewer import AIQualityReviewer
from xlsform_studio.app.artifacts import ArtifactBuilder
from xlsform_studio.app.logic_flow import LogicFlowBuilder
from xlsform_studio.app.workflow import Workflow
from xlsform_studio.models import (Choice, ChoiceList, FormSettings,
                                      Question, Questionnaire)
from xlsform_studio.parsers.excel_parser import ExcelParser


def _client(reply: dict) -> DeepSeekClient:
    client = DeepSeekClient(api_key="test-key")
    client.complete_json = lambda *a, **kw: reply  # type: ignore[method-assign]
    return client


def _form() -> Questionnaire:
    return Questionnaire(
        settings=FormSettings(form_title="Residency Survey", form_id="res",
                              version="3"),
        questions=[
            Question(name="resident", label="Are you a resident?",
                     xlsform_type="select_one yes_no", list_name="yes_no",
                     required=True, section="Screening"),
            Question(name="years_here", label="Years lived here",
                     xlsform_type="integer", section="Screening",
                     constraint=". >= 0 and . <= 100",
                     constraint_message="0-100 years.",
                     relevant="${resident}='1'"),
            Question(name="notes", label="Notes", xlsform_type="text",
                     hint="Optional comments.", section="Details"),
        ],
        choice_lists={"yes_no": ChoiceList("yes_no", [
            Choice("1", "Yes"), Choice("0", "No")])})


# --- D1: reverse engineering round-trip --------------------------------------------
def test_xlsform_round_trip_preserves_the_form(tmp_path):
    """Acceptance criterion: a form the tool exports can be read back with
    names, types, logic, constraints and choices intact."""
    original = Workflow().run(_form(), write_outputs=False)
    xlsx = tmp_path / "exported.xlsx"
    xlsx.write_bytes(original.xlsform_bytes)

    read_back = ExcelParser().parse(xlsx)
    by_name = {q.name: q for q in read_back.questions if not q.is_structural}
    assert set(by_name) >= {"resident", "years_here", "notes"}
    assert by_name["years_here"].relevant == "${resident}='1'"
    assert by_name["years_here"].constraint == ". >= 0 and . <= 100"
    assert by_name["resident"].required is True
    assert by_name["resident"].xlsform_type == "select_one yes_no"
    assert [c.name for c in read_back.choice_lists["yes_no"].choices] == \
        ["1", "0"]
    assert read_back.settings.form_title == "Residency Survey"


def test_reverse_engineering_full_pipeline(tmp_path):
    """XLSForm .xlsx in -> complete documentation package out."""
    original = Workflow().run(_form(), write_outputs=False)
    xlsx = tmp_path / "deployed_form.xlsx"
    xlsx.write_bytes(original.xlsform_bytes)

    result = Workflow().run_from_file(xlsx, output_dir=tmp_path / "docs",
                                      write_outputs=True)
    assert result.is_valid
    for key in ("enumerator_guide", "data_dictionary", "logic_map",
                "survey_instrument", "collection_plan",
                "variable_specification", "validation_report"):
        assert key in result.outputs, f"missing {key}"
        assert result.outputs[key].exists()


# --- D1: printable survey instrument (DOCX) ------------------------------------------
def test_survey_instrument_docx_content(tmp_path):
    import docx

    path = ArtifactBuilder().write_survey_instrument_docx(
        _form(), tmp_path / "instrument.docx")
    doc = docx.Document(str(path))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Residency Survey" in text
    assert "Screening" in text and "Details" in text
    assert "1. Are you a resident? *" in text          # numbered + required
    assert "○  Yes" in text and "○  No" in text        # tick options
    assert "Ask only when: resident = Yes" in text     # plain-words skip
    assert "Answer: ___" in text                       # open answer line
    assert "(0-100 years.)" in text                    # constraint message


def test_survey_instrument_in_output_package(tmp_path):
    result = Workflow().run(_form(), output_dir=tmp_path, write_outputs=True)
    path = result.outputs["survey_instrument"]
    assert path.exists() and path.suffix == ".docx"


# --- A8: indicator mapping --------------------------------------------------------------
def test_indicator_matrix_built_with_verified_references():
    reply = {"indicators": [
        {"indicator": "% households resident >5 years",
         "questions": ["resident", "years_here"],
         "aggregation": "district", "verification": "survey dataset"},
        {"indicator": "Ghost indicator", "questions": ["ghost_q"],
         "aggregation": "national", "verification": "x"}]}
    matrix, notes = AIIndicatorMapper(_client(reply)).map(
        _form(), survey_context="residency study")
    assert "# Indicator Matrix (draft)" in matrix
    assert "`resident`, `years_here`" in matrix
    assert "Ghost indicator" not in matrix             # no valid questions
    assert any("Discarded" in n for n in notes)
    assert any("Dropped indicator 'Ghost indicator'" in n for n in notes)


def test_indicators_end_to_end_writes_artifact(tmp_path):
    reply = {"indicators": [
        {"indicator": "% resident", "questions": ["resident"],
         "aggregation": "district", "verification": "dataset"}]}
    config = AIConfig(enabled=True, features=["indicators"],
                      survey_context="residency study")
    result = Workflow(ai_client=_client(reply)).run(
        _form(), ai_config=config, output_dir=tmp_path, write_outputs=True)
    assert result.indicator_matrix
    path = result.outputs.get("indicator_matrix")
    assert path is not None and path.exists()


# --- A1/A2/A14: expert-panel review brief ---------------------------------------------
def test_review_brief_covers_all_five_personas():
    captured = {}
    client = DeepSeekClient(api_key="k")

    def fake(system, user, **kw):
        captured["system"] = system
        return {"findings": []}
    client.complete_json = fake

    AIQualityReviewer(client).review(_form())
    for category in ("SEMANTIC", "NAMING/LABEL CLARITY",
                     "RESPONDENT EXPERIENCE", "ENUMERATOR EXPERIENCE",
                     "METHODOLOGY AND SEQUENCING"):
        assert category in captured["system"], f"missing {category}"


# --- D2 extension: Mermaid -----------------------------------------------------------------
def test_mermaid_output_and_embedding():
    mermaid = LogicFlowBuilder().to_mermaid(_form())
    assert mermaid.startswith("flowchart TD")
    assert 'resident -->|"Yes"| years_here' in mermaid
    md = ArtifactBuilder().logic_map_markdown(_form())
    assert "```mermaid" in md and "flowchart TD" in md


def test_mermaid_empty_without_logic():
    qn = Questionnaire(questions=[
        Question(name="a", label="A", xlsform_type="text")])
    assert LogicFlowBuilder().to_mermaid(qn) == ""
