"""Regression tests for validator blind spots found in the deep audit.

Each covered a case where an invalid XLSForm passed the *deterministic*
validator and was caught only by the optional pyxform deep check (or not at
all) - so with pyxform absent, a broken form shipped. The final test pins the
meta-invariant: the deterministic layer must reject what pyxform rejects, so
these gaps can't silently reopen.
"""

from __future__ import annotations

from xlsform_studio.models import (Choice, ChoiceList, FormSettings, Question,
                                   Questionnaire)
from xlsform_studio.validation.validator import Validator


def _validate(qn, deep=False):
    return Validator(deep=deep).validate(qn)


def _messages(report):
    return [f.message for f in report.findings]


# --- #1: group / repeat name collides with a question ------------------------
def test_group_name_colliding_with_question_is_rejected():
    qn = Questionnaire(
        settings=FormSettings(form_title="T", form_id="t", version="1"),
        questions=[Question(name="household", xlsform_type="begin group",
                            label="Household"),
                   Question(name="household", xlsform_type="integer",
                            label="Household size"),
                   Question(name="end_hh", xlsform_type="end group")])
    report = _validate(qn)
    assert not report.is_valid
    assert any("collides with a question" in m for m in _messages(report))


def test_two_groups_with_the_same_name_are_rejected():
    qn = Questionnaire(
        settings=FormSettings(form_title="T", form_id="t", version="1"),
        questions=[Question(name="grp", xlsform_type="begin group", label="A"),
                   Question(name="q1", xlsform_type="text", label="Q1"),
                   Question(name="e1", xlsform_type="end group"),
                   Question(name="grp", xlsform_type="begin group", label="B"),
                   Question(name="q2", xlsform_type="text", label="Q2"),
                   Question(name="e2", xlsform_type="end group")])
    report = _validate(qn)
    assert any("Duplicate group/repeat name" in m for m in _messages(report))


def test_matching_begin_end_group_pair_is_not_a_collision():
    """A normal group's begin+end share a name legitimately - no false alarm."""
    qn = Questionnaire(
        settings=FormSettings(form_title="T", form_id="t", version="1"),
        questions=[Question(name="grp", xlsform_type="begin group", label="A"),
                   Question(name="q1", xlsform_type="text", label="Q1"),
                   Question(name="grp", xlsform_type="end group")])
    report = _validate(qn)
    assert not any("Duplicate group" in m or "collides" in m
                   for m in _messages(report))


# --- #2: whitespace in choice codes ------------------------------------------
def test_space_in_select_multiple_code_is_error():
    qn = Questionnaire(
        settings=FormSettings(form_title="T", form_id="t", version="1"),
        questions=[Question(name="q", xlsform_type="select_multiple lst",
                            label="Pick", list_name="lst")],
        choice_lists={"lst": ChoiceList("lst", [Choice("has space", "Has space"),
                                                Choice("ok", "OK")])})
    report = _validate(qn)
    assert not report.is_valid
    assert any("whitespace" in m for m in _messages(report))


def test_space_in_select_one_code_is_only_a_warning():
    qn = Questionnaire(
        settings=FormSettings(form_title="T", form_id="t", version="1"),
        questions=[Question(name="q", xlsform_type="select_one lst",
                            label="Pick", list_name="lst")],
        choice_lists={"lst": ChoiceList("lst", [Choice("has space", "Has space"),
                                                Choice("ok", "OK")])})
    report = _validate(qn)
    assert report.is_valid                          # warning, not blocking
    assert any("whitespace" in f.message and f.level == "warning"
               for f in report.findings)


# --- #3: unsafe form_id ------------------------------------------------------
def test_unsafe_form_id_is_warned():
    qn = Questionnaire(
        settings=FormSettings(form_title="T", form_id="my form!", version="1"),
        questions=[Question(name="q", xlsform_type="text", label="Q")])
    report = _validate(qn)
    assert any("not a safe identifier" in m for m in _messages(report))


def test_valid_form_id_is_not_warned():
    qn = Questionnaire(
        settings=FormSettings(form_title="T", form_id="household_2026",
                              version="1"),
        questions=[Question(name="q", xlsform_type="text", label="Q")])
    report = _validate(qn)
    assert not any("safe identifier" in m for m in _messages(report))


# --- meta-invariant: don't regress below what pyxform catches ----------------
def test_deterministic_layer_catches_what_pyxform_catches():
    """A select_multiple code with a space is rejected by pyxform; the
    deterministic layer (deep=False) must reject it too, so the guarantee
    holds even when pyxform is not installed."""
    qn = Questionnaire(
        settings=FormSettings(form_title="T", form_id="t", version="1"),
        questions=[Question(name="q", xlsform_type="select_multiple lst",
                            label="Pick", list_name="lst")],
        choice_lists={"lst": ChoiceList("lst", [Choice("a b", "A B"),
                                                Choice("c", "C")])})
    assert not _validate(qn, deep=False).is_valid
