"""Tests for reviewable parsing: structured per-field Decisions, the
review table built from them, and applying human edits/approvals back
onto the form."""

import pytest

from xlsform_studio.app.review import (apply_review_edits, build_full_review,
                                        build_review_table)
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


# --- build_full_review (the whole-draft editor) --------------------------------
def test_full_review_covers_every_editable_field():
    q = Question(name="age", label="Age", xlsform_type="integer", required=True)
    q.add_decision("type", "integer", "high", "kw match")
    reviews = build_full_review(Questionnaire(questions=[q]))
    assert len(reviews) == 1
    names = {f.field_name for f in reviews[0].fields}
    # content + decision fields all present; choice_list absent (not a select)
    assert {"name", "label", "hint", "required", "type", "relevant",
            "constraint", "constraint_message", "calculation", "appearance",
            "default"} <= names
    assert "choice_list" not in names


def test_full_review_shows_choice_list_for_selects_only():
    sel = Question(name="sex", label="Sex", xlsform_type="select_one sexes",
                   list_name="sexes")
    txt = Question(name="note", label="Note", xlsform_type="text")
    reviews = build_full_review(Questionnaire(questions=[sel, txt]))
    by_name = {r.name: r for r in reviews}
    assert any(f.field_name == "choice_list" for f in by_name["sex"].fields)
    assert not any(f.field_name == "choice_list" for f in by_name["note"].fields)


def test_full_review_marks_bool_and_long_field_kinds():
    q = Question(name="age", label="Age", xlsform_type="integer")
    fields = {f.field_name: f for f in build_full_review(
        Questionnaire(questions=[q]))[0].fields}
    assert fields["required"].kind == "bool"
    assert fields["label"].kind == "long"
    assert fields["type"].kind == "text"


def test_full_review_surfaces_needs_attention_question_first():
    ok = Question(name="age", xlsform_type="integer", label="Age")
    ok.add_decision("type", "integer", "high", "ok")
    blank = Question(name="x", xlsform_type="text", label="X")
    blank.add_decision("relevant", "", "low", "ambiguous skip; left blank")
    reviews = build_full_review(Questionnaire(questions=[ok, blank]))
    assert reviews[0].name == "x"
    assert reviews[0].needs_attention


def test_full_review_edit_label_hint_required():
    q = Question(name="q1", label="Old", hint="", xlsform_type="text",
                 required=False)
    qn = Questionnaire(questions=[q])
    apply_review_edits(qn, {("q1", "label"): "New label",
                            ("q1", "hint"): "A hint",
                            ("q1", "required"): "yes"})
    assert q.label == "New label"
    assert q.hint == "A hint"
    assert q.required is True


def test_apply_review_rename_updates_references():
    q1 = Question(name="age", label="Age", xlsform_type="integer")
    q2 = Question(name="adult", label="Adult?", xlsform_type="text",
                  relevant="${age} >= 18", calculation="${age} * 12")
    qn = Questionnaire(questions=[q1, q2])
    notes = apply_review_edits(qn, {("age", "name"): "respondent_age"})
    assert q1.name == "respondent_age"
    assert q2.relevant == "${respondent_age} >= 18"
    assert q2.calculation == "${respondent_age} * 12"
    assert any("renamed" in n for n in notes)


def test_apply_review_rename_and_edit_same_question_in_one_batch():
    """Renaming a question and editing another of its fields in the same
    batch must both land - the rename must not orphan the other edit."""
    q0 = Question(name="age", label="Age", xlsform_type="integer")
    q1 = Question(name="adult", xlsform_type="text", relevant="${age} >= 18")
    qn = Questionnaire(questions=[q0, q1])
    apply_review_edits(qn, {("age", "name"): "respondent_age",
                            ("age", "label"): "Age in years"})
    assert q0.name == "respondent_age"
    assert q0.label == "Age in years"
    assert q1.relevant == "${respondent_age} >= 18"


def test_apply_review_rename_sanitises_free_text():
    q = Question(name="q1", label="Q", xlsform_type="text")
    qn = Questionnaire(questions=[q])
    apply_review_edits(qn, {("q1", "name"): "Household Size (persons)"})
    assert q.name == "household_size_persons"


def test_apply_review_rename_truncates_to_naming_rule_limit():
    """A human rename is capped at the same 32-char deterministic rule the
    AI author obeys - no drift between the author and the editor."""
    q = Question(name="q1", label="Q", xlsform_type="text")
    qn = Questionnaire(questions=[q])
    apply_review_edits(qn, {("q1", "name"): "a" * 50})
    assert len(q.name) <= 32
    assert q.name == "a" * 32


def test_apply_review_rename_rejects_duplicate():
    q1 = Question(name="age", xlsform_type="integer")
    q2 = Question(name="sex", xlsform_type="text")
    qn = Questionnaire(questions=[q1, q2])
    notes = apply_review_edits(qn, {("sex", "name"): "age"})
    assert q2.name == "sex"  # unchanged
    assert any("not renamed" in n for n in notes)


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
