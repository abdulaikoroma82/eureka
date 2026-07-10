"""Tests for the question classification engine (Module 2)."""

from xlsform_architect.engine.question_classifier import QuestionClassifier
from xlsform_architect.models import Question


def classify(label, choices=None, qtype=""):
    q = Question(raw_label=label, raw_choices=choices or [], xlsform_type=qtype)
    return QuestionClassifier().classify(q)


def test_yes_no():
    q = classify("Is the child enrolled in OTP?", ["Yes", "No"])
    assert q.xlsform_type == "select_one yes_no"


def test_select_one_multi_options():
    q = classify("What is the child's sex?", ["Male", "Female"])
    assert q.base_type == "select_one"


def test_select_multiple_from_wording():
    q = classify("Select all foods eaten yesterday", ["Rice", "Beans", "Meat"])
    assert q.base_type == "select_multiple"


def test_age_is_integer():
    assert classify("Child age in months").xlsform_type == "integer"


def test_weight_is_decimal():
    assert classify("Child weight in kg").xlsform_type == "decimal"


def test_muac_is_decimal():
    assert classify("MUAC measurement").xlsform_type == "decimal"


def test_date():
    assert classify("Date of admission").xlsform_type == "date"


def test_gps():
    assert classify("Record GPS location").xlsform_type == "geopoint"


def test_photo():
    assert classify("Take a photo of the child").xlsform_type == "image"


def test_fallback_text():
    assert classify("Any additional remarks").xlsform_type == "text"


def test_explicit_type_preserved():
    q = classify("Whatever", qtype="barcode")
    assert q.xlsform_type == "barcode"
