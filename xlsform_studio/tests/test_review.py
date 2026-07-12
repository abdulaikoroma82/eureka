"""Tests for reviewable parsing: structured per-field Decisions, the
review table built from them, and applying human edits/approvals back
onto the form."""

import pytest

from xlsform_studio.app.review import apply_review_edits, build_review_table
from xlsform_studio.app.workflow import Workflow
from xlsform_studio.engine.constraint_engine import ConstraintEngine
from xlsform_studio.engine.logic_engine import LogicEngine
from xlsform_studio.engine.question_classifier import QuestionClassifier
from xlsform_studio.engine.rule_engine import RuleEngine
from xlsform_studio.models import Question, Questionnaire


# --- Question.add_decision ---------------------------------------------------
def test_add_decision_records_both_structured_and_prose():
    q = Question(name="a")
    q.add_decision("type", "integer", "high", "Type inferred from keyword match.")
    assert q.decisions[0].field_name == "type"
    assert q.decisions[0].value == "integer"
    assert q.decisions[0].confidence == "high"
    assert "Type inferred from keyword match." in q.assumptions


def test_add_decision_rejects_bad_confidence():
    q = Question(name="a")
    with pytest.raises(ValueError):
        q.add_decision("type", "integer", "certain", "x")


# --- classifier decisions -----------------------------------------------------
def test_classifier_keyword_match_is_high_confidence():
    q = Question(raw_label="Respondent age")
    QuestionClassifier().classify(q)
    type_decisions = [d for d in q.decisions if d.field_name == "type"]
    assert type_decisions and type_decisions[-1].confidence == "high"
    assert type_decisions[-1].value == "integer"


def test_classifier_fallback_to_text_is_low_confidence():
    q = Question(raw_label="Something entirely unclassifiable xyzzy")
    QuestionClassifier().classify(q)
    type_decisions = [d for d in q.decisions if d.field_name == "type"]
    assert type_decisions and type_decisions[-1].confidence == "low"
    assert type_decisions[-1].value == "text"


def test_classifier_yes_no_records_type_and_choice_list():
    q = Question(raw_label="Is the child enrolled?", raw_choices=["Yes", "No"])
    QuestionClassifier().classify(q)
    fields = {d.field_name: d for d in q.decisions}
    assert fields["type"].confidence == "high"
    assert fields["choice_list"].value == "yes_no"
    assert fields["choice_list"].confidence == "high"


# --- logic engine: conservative NL compilation --------------------------------
def test_logic_engine_compiled_is_medium_confidence():
    prev = Question(name="enrolled", xlsform_type="select_one yes_no")
    q = Question(raw_label="Admission date", logic="ask if yes")
    LogicEngine().resolve(q, previous=prev)
    rel = [d for d in q.decisions if d.field_name == "relevant"][-1]
    assert rel.confidence == "medium"
    assert rel.value == "${enrolled}='1'"


def test_logic_engine_uncompilable_is_low_confidence_blank_value():
    """The conservative-NL principle: an ambiguous instruction must not
    produce a guessed expression - it surfaces as a blank, low-confidence
    review item instead."""
    q = Question(raw_label="X", logic="if the moon is full")
    LogicEngine().resolve(q)
    rel = [d for d in q.decisions if d.field_name == "relevant"][-1]
    assert rel.confidence == "low"
    assert rel.value == ""
    assert q.relevant == ""


def test_logic_engine_skip_jump_is_low_confidence_blank_value():
    q = Question(raw_label="X", logic="skip to question 12")
    LogicEngine().resolve(q)
    rel = [d for d in q.decisions if d.field_name == "relevant"][-1]
    assert rel.confidence == "low"
    assert rel.value == ""


# --- constraint engine ---------------------------------------------------------
def test_constraint_template_match_is_medium_confidence():
    q = Question(raw_label="Respondent age", xlsform_type="integer")
    ConstraintEngine().apply(q)
    con = [d for d in q.decisions if d.field_name == "constraint"][-1]
    assert con.confidence == "medium"
    assert con.value == q.constraint


def test_constraint_generic_default_is_low_confidence():
    q = Question(raw_label="Some date field", xlsform_type="date")
    ConstraintEngine().apply(q)
    con = [d for d in q.decisions if d.field_name == "constraint"][-1]
    assert con.confidence == "low"


# --- build_review_table --------------------------------------------------------
def _compiled_form():
    qn = Questionnaire(questions=[
        Question(raw_label="Is the respondent literate?", raw_choices=["Yes", "No"]),
        Question(raw_label="Admission date", logic="ask if yes"),
        Question(raw_label="Respondent age"),
        Question(raw_label="Complicated skip", logic="if the moon is full"),
    ])
    qn, _ = RuleEngine().compile(qn)
    return qn


def test_review_table_surfaces_needs_attention_rows_first():
    rows = build_review_table(_compiled_form())
    assert rows[0].needs_attention is True
    assert rows[0].field_name == "relevant"
    assert all(not r.needs_attention for r in rows[1:])


def test_review_table_dedupes_to_latest_decision_per_field():
    q = Question(name="a")
    q.add_decision("type", "text", "low", "defaulted")
    q.add_decision("type", "date", "high", "AI reclassified")
    qn = Questionnaire(questions=[q])
    rows = build_review_table(qn)
    type_rows = [r for r in rows if r.field_name == "type"]
    assert len(type_rows) == 1
    assert type_rows[0].value == "date"
    assert type_rows[0].confidence == "high"


def test_review_table_skips_structural_rows():
    qn = Questionnaire(questions=[
        Question(name="grp", xlsform_type="begin group", label="G")])
    assert build_review_table(qn) == []


# --- apply_review_edits ---------------------------------------------------------
def test_apply_review_edits_fills_in_blank_relevant():
    qn = _compiled_form()
    skip_q = next(q for q in qn.questions if q.name == "complicated_skip")
    edits = {("complicated_skip", "relevant"): "${respondent_age}>=18"}
    notes = apply_review_edits(qn, edits)
    assert skip_q.relevant == "${respondent_age}>=18"
    assert any("edited" in n for n in notes)
    latest = [d for d in skip_q.decisions if d.field_name == "relevant"][-1]
    assert latest.confidence == "high"
    assert "Reviewed and edited by a human." in skip_q.assumptions


def test_apply_review_edits_approve_unchanged_still_records_decision():
    qn = _compiled_form()
    q = next(q for q in qn.questions if q.name == "respondent_age")
    original = q.xlsform_type
    notes = apply_review_edits(qn, {("respondent_age", "type"): original})
    assert q.xlsform_type == original
    assert any("approved" in n for n in notes)


def test_apply_review_edits_choice_list_rewrites_type_token():
    q = Question(name="q", xlsform_type="select_one old_list", list_name="old_list")
    qn = Questionnaire(questions=[q])
    apply_review_edits(qn, {("q", "choice_list"): "new_list"})
    assert q.list_name == "new_list"
    assert q.xlsform_type == "select_one new_list"


def test_apply_review_edits_unknown_question_is_noted_not_raised():
    qn = _compiled_form()
    notes = apply_review_edits(qn, {("ghost", "type"): "integer"})
    assert any("no longer exists" in n for n in notes)


# --- Workflow integration --------------------------------------------------------
def test_workflow_run_populates_review_table():
    result = Workflow().run_from_dict(
        {"settings": {"form_title": "T", "form_id": "t"},
         "survey": [{"question": "Respondent age"}]},
        write_outputs=False)
    assert result.review_table
    assert any(r.field_name == "type" for r in result.review_table)


def test_workflow_apply_review_edits_rebuilds_form():
    result = Workflow().run_from_dict(
        {"settings": {"form_title": "T", "form_id": "t"},
         "survey": [
             {"question": "X", "logic": "if the moon is full"},
             {"question": "Respondent age"},
         ]},
        write_outputs=False)
    skip_row = next(r for r in result.review_table
                    if r.field_name == "relevant" and r.needs_attention)
    before_bytes = result.xlsform_bytes
    Workflow().apply_review_edits(
        result, {(skip_row.question, "relevant"): "${respondent_age}>=18"})
    q = next(q for q in result.questionnaire.questions
            if q.name == skip_row.question)
    assert q.relevant == "${respondent_age}>=18"
    assert result.xlsform_bytes != before_bytes
    assert not any(r.needs_attention for r in result.review_table
                  if r.question == skip_row.question)
