"""Tests for the skip-pattern flowchart (LogicFlowBuilder): edge derivation,
condition prettifying, the ASCII branch tree, DOT output, and the artefact
wiring into logic_map.md and the output package."""

from __future__ import annotations

from xlsform_architect.app.artifacts import ArtifactBuilder
from xlsform_architect.app.logic_flow import LogicFlowBuilder
from xlsform_architect.app.workflow import Workflow
from xlsform_architect.models import (Choice, ChoiceList, FormSettings,
                                      Question, Questionnaire)


def _form() -> Questionnaire:
    """resident gates years_lived; marital gates spouse_name; age is free."""
    return Questionnaire(
        settings=FormSettings(form_title="T", form_id="t"),
        questions=[
            Question(name="resident", label="Are you a resident of this district?",
                     xlsform_type="select_one yes_no", list_name="yes_no"),
            Question(name="years_lived", label="How many years have you lived here?",
                     xlsform_type="integer", relevant="${resident}='1'"),
            Question(name="age", label="Respondent age", xlsform_type="integer"),
            Question(name="marital", label="Marital status",
                     xlsform_type="select_one m", list_name="m"),
            Question(name="spouse_name", label="Spouse name",
                     xlsform_type="text", relevant="${marital}='2'"),
        ],
        choice_lists={
            "yes_no": ChoiceList("yes_no", [Choice("1", "Yes"),
                                            Choice("0", "No")]),
            "m": ChoiceList("m", [Choice("1", "Single"), Choice("2", "Married"),
                                  Choice("3", "Divorced")]),
        })


# --- edge derivation ------------------------------------------------------------
def test_edges_derived_from_relevant():
    edges = LogicFlowBuilder().edges(_form())
    assert [(e.source, e.target) for e in edges] == \
        [("resident", "years_lived"), ("marital", "spouse_name")]


def test_condition_codes_rendered_as_labels():
    edges = LogicFlowBuilder().edges(_form())
    assert edges[0].condition == "resident = Yes"      # '1' -> Yes
    assert edges[1].condition == "marital = Married"   # '2' -> Married


def test_compound_condition_yields_edge_per_source():
    qn = _form()
    qn.questions[4].relevant = "${resident}='1' and ${marital}='2'"
    edges = [e for e in LogicFlowBuilder().edges(qn)
             if e.target == "spouse_name"]
    assert {e.source for e in edges} == {"resident", "marital"}
    assert all(not e.sole_source for e in edges)
    assert all(e.condition == "resident = Yes and marital = Married"
              for e in edges)


def test_prettify_selected_inequality_and_not():
    qn = _form()
    qn.questions[1].relevant = "selected(${resident}, '1')"
    qn.questions[4].relevant = "not(${marital}='1')"
    edges = LogicFlowBuilder().edges(qn)
    assert edges[0].condition == "resident includes Yes"
    assert edges[1].condition == "marital ≠ Single"


def test_numeric_comparison_kept_verbatim():
    qn = Questionnaire(questions=[
        Question(name="age", label="Age", xlsform_type="integer"),
        Question(name="work", label="Occupation", xlsform_type="text",
                 relevant="${age} > 17")])
    edges = LogicFlowBuilder().edges(qn)
    assert edges[0].condition == "age > 17"


def test_self_and_unknown_references_ignored():
    qn = Questionnaire(questions=[
        Question(name="a", label="A", xlsform_type="integer",
                 relevant="${a} > 1 and ${ghost} = '2'")])
    assert LogicFlowBuilder().edges(qn) == []


# --- ASCII branch tree ------------------------------------------------------------
def test_ascii_tree_shape():
    text = LogicFlowBuilder().to_ascii(_form())
    assert "resident — Are you a resident of this district?" in text
    # branch label is shortened relative to its own node: "Yes", not
    # "resident = Yes"
    assert "├── Yes → years_lived" in text
    # the otherwise branch points at the next question NOT gated on resident
    assert "└── otherwise → age" in text
    assert "├── Married → spouse_name" in text
    assert "└── otherwise → (end of form)" in text


def test_ascii_groups_targets_sharing_a_condition():
    qn = _form()
    qn.questions[2].relevant = "${resident}='1'"     # age now gated too
    text = LogicFlowBuilder().to_ascii(qn)
    assert "├── Yes → years_lived, age" in text
    assert "└── otherwise → marital" in text


def test_ascii_empty_when_no_logic():
    qn = Questionnaire(questions=[
        Question(name="a", label="A", xlsform_type="integer")])
    assert LogicFlowBuilder().to_ascii(qn) == ""


# --- DOT output --------------------------------------------------------------------
def test_dot_contains_nodes_and_labelled_edges():
    dot = LogicFlowBuilder().to_dot(_form())
    assert dot.startswith("digraph skip_logic {")
    assert '"resident" -> "years_lived" [label="Yes"];' in dot
    assert '"marital" -> "spouse_name" [label="Married"];' in dot
    # uninvolved questions stay out of the picture
    assert '"age"' not in dot


def test_dot_escapes_quotes_in_labels():
    qn = Questionnaire(questions=[
        Question(name="a", label='The "big" one', xlsform_type="integer"),
        Question(name="b", label="B", xlsform_type="text",
                 relevant="${a} > 1")])
    dot = LogicFlowBuilder().to_dot(qn)
    assert '\\"big\\"' in dot


def test_dot_empty_when_no_logic():
    qn = Questionnaire(questions=[
        Question(name="a", label="A", xlsform_type="integer")])
    assert LogicFlowBuilder().to_dot(qn) == ""


# --- artefact wiring ------------------------------------------------------------------
def test_logic_map_markdown_embeds_flowchart():
    md = ArtifactBuilder().logic_map_markdown(_form())
    assert "## Skip-pattern flowchart" in md
    assert "├── Yes → years_lived" in md
    assert "```text" in md


def test_logic_map_markdown_omits_flowchart_without_logic():
    qn = Questionnaire(questions=[
        Question(name="a", label="A", xlsform_type="integer")])
    md = ArtifactBuilder().logic_map_markdown(qn)
    assert "Skip-pattern flowchart" not in md
    assert "_No conditional questions._" in md


def test_workflow_writes_dot_artifact(tmp_path):
    result = Workflow().run(_form(), form_title="T", form_id="t",
                            output_dir=tmp_path, write_outputs=True)
    dot_path = result.outputs.get("logic_flow")
    assert dot_path is not None and dot_path.exists()
    assert "digraph skip_logic" in dot_path.read_text(encoding="utf-8")


def test_workflow_skips_dot_artifact_without_logic(tmp_path):
    qn = Questionnaire(questions=[
        Question(name="a", label="Age", xlsform_type="integer")])
    result = Workflow().run(qn, form_title="T", form_id="t",
                            output_dir=tmp_path, write_outputs=True)
    assert "logic_flow" not in result.outputs
