"""Tests for the calculation engine (Module 7)."""

from xlsform_architect.engine.calculation_engine import CalculationEngine
from xlsform_architect.models import Question, Questionnaire


def _find(calcs, name):
    return next((c for c in calcs if c.name == name), None)


def test_muac_classification_generated():
    qn = Questionnaire(questions=[
        Question(name="muac", raw_label="MUAC (cm)", xlsform_type="decimal")])
    calcs = CalculationEngine().build(qn)
    muac_class = _find(calcs, "muac_class")
    assert muac_class is not None
    assert "11.5" in muac_class.calculation
    assert "${muac}" in muac_class.calculation


def test_bmi_generated_from_weight_height():
    qn = Questionnaire(questions=[
        Question(name="weight", raw_label="Weight", xlsform_type="decimal"),
        Question(name="height", raw_label="Height", xlsform_type="decimal")])
    bmi = _find(CalculationEngine().build(qn), "bmi")
    assert bmi is not None
    assert "${weight}" in bmi.calculation and "${height}" in bmi.calculation


def test_age_months_from_dob():
    qn = Questionnaire(questions=[
        Question(name="dob", raw_label="Date of birth", xlsform_type="date")])
    age = _find(CalculationEngine().build(qn), "age_months")
    assert age is not None
    assert "${dob}" in age.calculation


def test_imam_admission_from_muac_and_oedema():
    qn = Questionnaire(questions=[
        Question(name="muac", raw_label="MUAC", xlsform_type="decimal"),
        Question(name="oedema", raw_label="Bilateral oedema", xlsform_type="select_one oedema")])
    adm = _find(CalculationEngine().build(qn), "imam_admission")
    assert adm is not None
    assert adm.xlsform_type == "calculate"


def test_no_sources_no_calcs():
    qn = Questionnaire(questions=[
        Question(name="name", raw_label="Name", xlsform_type="text")])
    assert CalculationEngine().build(qn) == []
