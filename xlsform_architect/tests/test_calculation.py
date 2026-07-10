"""Tests for the calculation engine (Module 7)."""

from xlsform_architect.engine.calculation_engine import CalculationEngine
from xlsform_architect.models import Question, Questionnaire


def _find(calcs, name):
    return next((c for c in calcs if c.name == name), None)


def test_age_years_from_dob():
    qn = Questionnaire(questions=[
        Question(name="dob", raw_label="Date of birth", xlsform_type="date")])
    age = _find(CalculationEngine().build(qn), "age_years")
    assert age is not None
    assert age.xlsform_type == "calculate"
    assert "${dob}" in age.calculation


def test_age_single_line_expression():
    qn = Questionnaire(questions=[
        Question(name="dob", raw_label="Date of birth", xlsform_type="date")])
    age = _find(CalculationEngine().build(qn), "age_years")
    assert "\n" not in age.calculation


def test_no_dob_no_calcs():
    qn = Questionnaire(questions=[
        Question(name="full_name", raw_label="Full name", xlsform_type="text")])
    assert CalculationEngine().build(qn) == []


def test_existing_age_not_duplicated():
    qn = Questionnaire(questions=[
        Question(name="dob", raw_label="Date of birth", xlsform_type="date"),
        Question(name="age_years", raw_label="Age", xlsform_type="integer")])
    assert _find(CalculationEngine().build(qn), "age_years") is None
