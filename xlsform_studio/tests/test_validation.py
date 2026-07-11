"""Tests for the validation system (Module 9)."""

from xlsform_studio.models import (Choice, ChoiceList, Question,
                                      Questionnaire)
from xlsform_studio.validation.validator import Validator


def test_valid_form_passes():
    qn = Questionnaire(questions=[
        Question(name="age", xlsform_type="integer", label="Age")])
    assert Validator().validate(qn).is_valid


def test_duplicate_names_flagged():
    qn = Questionnaire(questions=[
        Question(name="age", xlsform_type="integer", label="Age"),
        Question(name="age", xlsform_type="integer", label="Age again")])
    report = Validator().validate(qn)
    assert not report.is_valid
    assert any("Duplicate" in f.message for f in report.errors)


def test_broken_reference_flagged():
    qn = Questionnaire(questions=[
        Question(name="a", xlsform_type="integer", label="A"),
        Question(name="b", xlsform_type="integer", label="B", relevant="${ghost}>1")])
    report = Validator().validate(qn)
    assert any("unknown variable" in f.message for f in report.errors)


def test_missing_choice_list_flagged():
    qn = Questionnaire(questions=[
        Question(name="s", xlsform_type="select_one nolist", label="S", list_name="nolist")])
    report = Validator().validate(qn)
    assert any("undefined list" in f.message for f in report.errors)


def test_invalid_identifier_flagged():
    qn = Questionnaire(questions=[
        Question(name="1bad", xlsform_type="integer", label="X")])
    report = Validator().validate(qn)
    assert any("valid ODK/XML identifier" in f.message for f in report.errors)


def test_reserved_name_flagged():
    qn = Questionnaire(questions=[
        Question(name="name", xlsform_type="text", label="Name")])
    report = Validator().validate(qn)
    assert any("reserved" in f.message for f in report.errors)


def test_compatibility_matrix():
    qn = Questionnaire(questions=[
        Question(name="age", xlsform_type="integer", label="Age")])
    matrix = Validator().validate(qn).compatibility
    # Every platform profile in the knowledge pack gets a verdict, and a
    # plain integer question is compatible everywhere.
    assert {"kobo", "surveycto", "odk", "ona", "commcare"} <= set(matrix)
    assert all(matrix.values())


def test_empty_choice_list_flagged():
    qn = Questionnaire(
        questions=[Question(name="s", xlsform_type="select_one empty", label="S",
                            list_name="empty")],
        choice_lists={"empty": ChoiceList("empty", [])})
    report = Validator().validate(qn)
    assert any("is empty" in f.message for f in report.errors)
