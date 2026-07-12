"""Tests for the Finding confidence dimension.

Every Finding is tagged with how sure the tool is about it, independent of
severity ("error"/"warning"/"info"): confirmed by a real platform toolchain
(pyxform), checked by this tool's own deterministic rules, heuristically
inferred (pattern-matching or AI - review needed), or unsupported/passed
through unchecked. These tests pin the classification for each validator
family so a future change can't silently blur "we verified this" with
"we're guessing"."""

from xlsform_studio.models import (Choice, ChoiceList, FormSettings, Question,
                                   Questionnaire)
from xlsform_studio.validation.choice_auditor import ChoiceAuditor
from xlsform_studio.validation.consistency_validator import ConsistencyValidator
from xlsform_studio.validation.expression_validator import ExpressionValidator
from xlsform_studio.validation.logic_validator import LogicValidator
from xlsform_studio.validation.pyxform_validator import PyxformValidator
from xlsform_studio.validation.report_generator import (CONFIDENCE_LEVELS,
                                                         Finding)
from xlsform_studio.validation.structure_validator import StructureValidator


def test_confidence_defaults_to_checked():
    f = Finding("error", "logic", "boom")
    assert f.confidence == "checked"


def test_confidence_rejects_unknown_value():
    import pytest
    with pytest.raises(ValueError):
        Finding("error", "logic", "boom", confidence="vibes")


def test_confidence_levels_are_stable():
    """Pin the four-level vocabulary itself - a new level should be a
    deliberate, reviewed addition, not an accidental typo."""
    assert CONFIDENCE_LEVELS == ("confirmed", "checked", "heuristic",
                                 "unsupported")


def test_to_dict_includes_confidence():
    assert Finding("warning", "logic", "x").to_dict()["confidence"] == "checked"


# --- deterministic rule validators: "checked" -------------------------------
def test_structure_validator_findings_are_checked():
    qn = Questionnaire(questions=[Question(name="", xlsform_type="", label="x")])
    findings = StructureValidator().validate(qn)
    assert findings and all(f.confidence == "checked" for f in findings)


def test_logic_validator_findings_are_checked():
    qn = Questionnaire(questions=[
        Question(name="a", xlsform_type="integer", label="A"),
        Question(name="a", xlsform_type="integer", label="A again")])
    findings = LogicValidator().validate(qn)
    assert findings and all(f.confidence == "checked" for f in findings)


def test_expression_syntax_error_is_checked():
    qn = Questionnaire(
        settings=FormSettings(form_title="T", form_id="t"),
        questions=[Question(name="s", xlsform_type="integer", label="S",
                            constraint=". >< 5")])
    findings = ExpressionValidator().validate(qn)
    assert any(f.confidence == "checked" and f.level == "error"
              for f in findings)


# --- pattern-matched inferences: "heuristic" --------------------------------
def test_choice_auditor_scale_gap_is_heuristic():
    qn = Questionnaire(
        questions=[Question(name="q", label="Q?",
                            xlsform_type="select_one scale", list_name="scale")],
        choice_lists={"scale": ChoiceList("scale", [
            Choice("1", "Very good"), Choice("2", "Good"),
            Choice("3", "Poor"), Choice("4", "Very poor")])})
    findings = ChoiceAuditor().validate(qn)
    scale_findings = [f for f in findings if "scale" in f.message]
    assert scale_findings and all(f.confidence == "heuristic"
                                  for f in scale_findings)


def test_choice_auditor_other_specify_is_checked():
    """Unlike the pattern-matched checks, a missing Other/specify follow-up
    is a hard structural fact, not a guess."""
    qn = Questionnaire(
        questions=[Question(name="q", label="Q?",
                            xlsform_type="select_one opts", list_name="opts")],
        choice_lists={"opts": ChoiceList("opts", [
            Choice("1", "Yes"), Choice("other", "Other")])})
    findings = ChoiceAuditor().validate(qn)
    assert findings and all(f.confidence == "checked" for f in findings)


def test_near_identical_lists_is_heuristic():
    # 9 shared choices + 1 differing choice each -> 9/11 = 81.8% overlap,
    # above the near-identical threshold.
    shared = [Choice(str(i), f"Option {i}") for i in range(9)]
    qn = Questionnaire(choice_lists={
        "a": ChoiceList("a", shared + [Choice("9a", "Only in A")]),
        "b": ChoiceList("b", shared + [Choice("9b", "Only in B")])})
    findings = ConsistencyValidator().validate(qn)
    assert findings and all(f.confidence == "heuristic" for f in findings)


def test_unrecognised_function_is_unsupported():
    qn = Questionnaire(
        settings=FormSettings(form_title="T", form_id="t"),
        questions=[Question(name="a", xlsform_type="integer", label="A",
                            relevant="frobnicate(${a})")])
    findings = ExpressionValidator().validate(qn)
    assert any(f.confidence == "unsupported" for f in findings)


# --- XPath union ('|'): valid-but-unmodeled syntax, downgraded not rejected -
def test_valid_union_expression_is_info_not_error():
    """A valid-but-unsupported XPath union must not block validation: it
    is an info-level, unsupported-confidence finding, not an error."""
    qn = Questionnaire(
        settings=FormSettings(form_title="T", form_id="t"),
        questions=[Question(
            name="city", xlsform_type="select_one cities", label="City",
            list_name="cities",
            choice_filter="instance('a')/root/item | instance('b')/root/item")])
    findings = ExpressionValidator().validate(qn)
    assert not any(f.level == "error" for f in findings)
    union_findings = [f for f in findings if "union" in f.message.lower()]
    assert union_findings
    assert all(f.level == "info" and f.confidence == "unsupported"
              for f in union_findings)


def test_malformed_expression_inside_union_is_still_an_error():
    """The union downgrade must never mask a genuinely malformed side."""
    qn = Questionnaire(
        settings=FormSettings(form_title="T", form_id="t"),
        questions=[Question(name="a", xlsform_type="integer", label="A",
                            relevant="${a} >< 5 | ${b}")])
    findings = ExpressionValidator().validate(qn)
    assert any(f.level == "error" and f.confidence == "checked"
              for f in findings)
    assert not any("not fully checked" in f.message for f in findings)


def test_plain_malformed_expression_unaffected_by_union_support():
    """Regression guard: adding '|' handling must not change the outcome
    for expressions that don't use '|' at all."""
    qn = Questionnaire(
        settings=FormSettings(form_title="T", form_id="t"),
        questions=[Question(name="s", xlsform_type="integer", label="S",
                            constraint=". >< 5")])
    findings = ExpressionValidator().validate(qn)
    assert any(f.level == "error" and f.confidence == "checked"
              for f in findings)


def test_check_detailed_reports_union_reason():
    v = ExpressionValidator()
    error, unknown, unsupported = v.check_detailed("${a} | ${b}")
    assert error is None
    assert unsupported and "union" in unsupported.lower()


def test_check_two_tuple_stays_backward_compatible_for_union():
    """check() must remain a plain (error, unknown_funcs) 2-tuple even for
    union expressions - existing callers unpack exactly two values."""
    v = ExpressionValidator()
    error, unknown = v.check("${a} | ${b}")
    assert error is None
    assert unknown == []


# --- pyxform (real toolchain): "confirmed" or "unsupported" ----------------
def test_pyxform_success_is_confirmed():
    v = PyxformValidator()
    if not v.available:
        return  # pyxform not installed in this environment - nothing to check
    qn = Questionnaire(
        settings=FormSettings(form_title="T", form_id="t"),
        questions=[Question(name="age", xlsform_type="integer", label="Age")])
    findings = v.validate(qn)
    assert findings and all(f.confidence == "confirmed" for f in findings)


def test_pyxform_not_installed_is_unsupported(monkeypatch):
    v = PyxformValidator()
    monkeypatch.setattr(v, "_convert", None)
    qn = Questionnaire(
        settings=FormSettings(form_title="T", form_id="t"),
        questions=[Question(name="age", xlsform_type="integer", label="Age")])
    findings = v.validate(qn)
    assert findings and all(f.confidence == "unsupported" for f in findings)
