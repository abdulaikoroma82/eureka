"""Tests for the deep (pyxform) and extended structural validation."""

import pytest

from xlsform_architect.models import FormSettings, Question, Questionnaire
from xlsform_architect.validation.pyxform_validator import PyxformValidator
from xlsform_architect.validation.structure_validator import StructureValidator
from xlsform_architect.validation.validator import Validator
from xlsform_architect.validation.xlsform_validator import XLSFormValidator

pyxform_available = PyxformValidator().available
requires_pyxform = pytest.mark.skipif(not pyxform_available,
                                      reason="pyxform not installed")


def _valid_form():
    return Questionnaire(
        settings=FormSettings(form_title="T", form_id="t"),
        questions=[Question(name="age", xlsform_type="integer", label="Age")])


# --- pyxform deep check ----------------------------------------------------
@requires_pyxform
def test_deep_passes_valid_form():
    findings = PyxformValidator().validate(_valid_form())
    assert all(f.level != "error" for f in findings)
    assert any("Deep validation passed" in f.message for f in findings)


@requires_pyxform
def test_deep_rejects_bad_reference():
    qn = Questionnaire(
        settings=_valid_form().settings,
        questions=[Question(name="a", xlsform_type="integer", label="A",
                            relevant="${ghost} > 1")])
    findings = PyxformValidator().validate(qn)
    assert any(f.level == "error" for f in findings)


@requires_pyxform
def test_deep_flips_compatibility_on_error():
    qn = Questionnaire(
        settings=_valid_form().settings,
        questions=[Question(name="a", xlsform_type="integer", label="A",
                            relevant="${ghost} > 1")])
    report = Validator().validate(qn)
    assert report.compatibility == {"kobo": False, "surveycto": False, "odk": False}
    assert report.deep_ran is True


def test_deep_can_be_disabled():
    report = Validator(deep=False).validate(_valid_form())
    assert report.deep_ran is False
    assert not any("Deep validation" in f.message for f in report.findings)


def test_unavailable_pyxform_returns_info(monkeypatch):
    v = PyxformValidator()
    monkeypatch.setattr(v, "_convert", None)
    findings = v.validate(_valid_form())
    assert findings and findings[0].level == "info"


# --- group / repeat balance ------------------------------------------------
def test_unclosed_group_flagged():
    qn = Questionnaire(questions=[
        Question(name="grp", xlsform_type="begin group", label="G"),
        Question(name="x", xlsform_type="integer", label="X")])
    findings = StructureValidator().validate(qn)
    assert any("never closed" in f.message for f in findings)


def test_unmatched_end_flagged():
    qn = Questionnaire(questions=[
        Question(name="x", xlsform_type="integer", label="X"),
        Question(name="grp", xlsform_type="end group", label="")])
    findings = StructureValidator().validate(qn)
    assert any("without a matching opener" in f.message for f in findings)


def test_mismatched_markers_flagged():
    qn = Questionnaire(questions=[
        Question(name="grp", xlsform_type="begin group", label="G"),
        Question(name="rep", xlsform_type="end repeat", label="")])
    findings = StructureValidator().validate(qn)
    assert any("does not match" in f.message for f in findings)


def test_balanced_group_ok():
    qn = Questionnaire(questions=[
        Question(name="grp", xlsform_type="begin group", label="G"),
        Question(name="x", xlsform_type="integer", label="X"),
        Question(name="grp_end", xlsform_type="end group", label="")])
    findings = StructureValidator().validate(qn)
    assert not any(f.level == "error" for f in findings)


# --- appearance & reserved words -------------------------------------------
def test_unknown_appearance_warned():
    qn = Questionnaire(questions=[
        Question(name="x", xlsform_type="text", label="X", appearance="bogus-mode")])
    findings = XLSFormValidator().validate(qn)
    assert any("not a standard appearance" in f.message for f in findings)


def test_known_appearance_ok():
    qn = Questionnaire(questions=[
        Question(name="x", xlsform_type="text", label="X", appearance="multiline")])
    findings = XLSFormValidator().validate(qn)
    assert not any(f.level == "warning" and "appearance" in f.message for f in findings)


def test_columns_n_appearance_ok():
    qn = Questionnaire(questions=[
        Question(name="x", xlsform_type="select_one a", label="X",
                 list_name="a", appearance="columns-2")])
    findings = XLSFormValidator().validate(qn)
    assert not any("not a standard appearance" in f.message for f in findings)


def test_extended_reserved_word_flagged():
    qn = Questionnaire(questions=[
        Question(name="instance", xlsform_type="text", label="X")])
    findings = XLSFormValidator().validate(qn)
    assert any("reserved" in f.message for f in findings)
