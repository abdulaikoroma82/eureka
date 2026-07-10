"""Tests for the logic (Module 5) and constraint (Module 6) engines."""

from xlsform_architect.engine.constraint_engine import ConstraintEngine
from xlsform_architect.engine.logic_engine import LogicEngine
from xlsform_architect.models import Question


# --- logic engine ----------------------------------------------------------
def test_if_yes_references_previous():
    prev = Question(name="enrolled_otp", xlsform_type="select_one yes_no")
    q = Question(raw_label="Admission date", logic="ask if yes")
    expr = LogicEngine().resolve(q, previous=prev)
    assert expr == "${enrolled_otp}='1'"


def test_if_no_references_previous():
    prev = Question(name="enrolled", xlsform_type="select_one yes_no")
    q = Question(raw_label="Reason", logic="if no")
    assert LogicEngine().resolve(q, previous=prev) == "${enrolled}='0'"


def test_under_5_years_in_months():
    age = Question(name="child_age_months", raw_label="Child age in months",
                   xlsform_type="integer")
    q = Question(raw_label="Give MUAC", logic="if child is under 5 years")
    expr = LogicEngine().resolve(q, previous=None, known=[age, q])
    assert expr == "${child_age_months}<60"


def test_explicit_relevant_untouched():
    q = Question(raw_label="x", logic="if yes", relevant="${a}=1")
    assert LogicEngine().resolve(q) == "${a}=1"


def test_unresolvable_logic_logged():
    q = Question(raw_label="x", name="x", logic="only when the moon is full")
    LogicEngine().resolve(q)
    assert q.relevant == ""
    assert any("could not be auto-compiled" in a for a in q.assumptions)


# --- constraint engine -----------------------------------------------------
def test_age_months_constraint():
    q = Question(raw_label="Child age in months", xlsform_type="integer")
    ConstraintEngine().apply(q)
    assert q.constraint == ". >= 0 and . <= 60"


def test_percentage_constraint():
    q = Question(raw_label="Coverage percentage", xlsform_type="decimal")
    ConstraintEngine().apply(q)
    assert q.constraint == ". >= 0 and . <= 100"


def test_weight_constraint():
    q = Question(raw_label="Weight in kg", xlsform_type="decimal")
    ConstraintEngine().apply(q)
    assert q.constraint == ". > 0 and . <= 200"


def test_date_not_future():
    q = Question(raw_label="Admission date", xlsform_type="date")
    ConstraintEngine().apply(q)
    assert q.constraint == ". <= today()"


def test_explicit_constraint_preserved():
    q = Question(raw_label="Weight", xlsform_type="decimal", constraint=". > 1")
    ConstraintEngine().apply(q)
    assert q.constraint == ". > 1"
