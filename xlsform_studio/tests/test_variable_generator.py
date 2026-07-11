"""Tests for the variable naming engine (Module 3)."""

from xlsform_studio.engine.variable_generator import VariableGenerator


def test_basic_slug():
    gen = VariableGenerator()
    assert gen.generate("Child age in months") == "child_age_months"


def test_received_mms():
    gen = VariableGenerator()
    assert gen.generate("Mother received MMS") == "mother_recv_mms"


def test_no_spaces_lowercase():
    gen = VariableGenerator()
    name = gen.generate("Household Head Name")
    assert name == name.lower()
    assert " " not in name


def test_uniqueness_suffix():
    gen = VariableGenerator()
    a = gen.generate("Child age in months")
    b = gen.generate("Child age in months")
    assert a != b
    assert b.endswith("_2")


def test_leading_digit_prefixed():
    gen = VariableGenerator()
    name = gen.generate("24 hour recall")
    assert not name[0].isdigit()


def test_max_length_respected():
    gen = VariableGenerator()
    long_label = "This is an extremely long question label about nutrition and health outcomes"
    name = gen.generate(long_label)
    assert len(name) <= gen.max_length


def test_empty_label_falls_back():
    gen = VariableGenerator()
    assert gen.generate("???") == "question"
