"""Tests for the confidence-raising upgrades: expression syntax validation,
choice-value cross-checks, expanded logic patterns, expanded constraints,
and parser robustness (coded options, required markers, question numbers)."""

from xlsform_studio.app.workflow import Workflow
from xlsform_studio.engine.constraint_engine import ConstraintEngine
from xlsform_studio.engine.logic_engine import LogicEngine
from xlsform_studio.models import (Choice, ChoiceList, FormSettings,
                                      Question, Questionnaire)
from xlsform_studio.parsers.questionnaire_parser import QuestionnaireParser
from xlsform_studio.validation.expression_validator import ExpressionValidator
from xlsform_studio.validation.validator import Validator


# --- expression syntax validation --------------------------------------------
GOOD_EXPRESSIONS = [
    ". >= 0 and . <= 120",
    "${enrolled}='1'",
    "selected(${services}, 'clinic')",
    "(. <= today()) and (. >= ${start_date})",
    "if(${muac} < 11.5, 'sam', if(${muac} < 12.5, 'mam', 'normal'))",
    "int((today() - ${dob}) div 365.25)",
    "${a}!=${b} or not(${c}='x')",
    "regex(., '^[0-9]{7,15}$')",
    "-5 + ${x} * -2",
    "concat('a', \"b\", ${c})",
    "count-selected(${m}) >= 2",
    "jr:choice-name(${q}, '${q}')",
    "today()",
]

BAD_EXPRESSIONS = [
    ". >< 5",                  # doubled operator (the original hole)
    "${a} ${b}",               # missing operator
    "${a} >",                  # dangling operator
    "selected(${x} 'v')",      # missing comma
    "(${a} > 1",               # unbalanced open paren
    "${a} > 1)",               # unbalanced close paren
    "${a} = 'unclosed",        # unbalanced quote
    "${bad name}='1'",         # malformed reference
    "${a} and",                # trailing word operator
    "1, 2",                    # comma outside a call
    "selected(, 'v')",         # empty argument
    "${a} = = '1'",            # doubled equals
]


def test_expression_validator_accepts_all_good():
    v = ExpressionValidator()
    for expr in GOOD_EXPRESSIONS:
        err, _ = v.check(expr)
        assert err is None, f"false positive on {expr!r}: {err}"


def test_expression_validator_rejects_all_bad():
    v = ExpressionValidator()
    for expr in BAD_EXPRESSIONS:
        err, _ = v.check(expr)
        assert err is not None, f"missed malformed expression {expr!r}"


def test_expression_validator_unknown_function_is_warning_not_error():
    err, unknown = ExpressionValidator().check("frobnicate(${x})")
    assert err is None
    assert unknown == ["frobnicate"]


def test_malformed_constraint_now_fails_validation():
    """Regression for the confirmed hole: '. >< 5' used to pass everything."""
    qn = Questionnaire(
        settings=FormSettings(form_title="T", form_id="t"),
        questions=[Question(name="score", xlsform_type="integer",
                            label="Score", constraint=". >< 5")])
    report = Validator(deep=False).validate(qn)
    assert not report.is_valid
    assert any(f.category == "expression" for f in report.errors)


# --- choice-value cross-check --------------------------------------------------
def _sex_form(relevant: str) -> Questionnaire:
    return Questionnaire(
        settings=FormSettings(form_title="T", form_id="t"),
        questions=[
            Question(name="sex", xlsform_type="select_one sexes", label="Sex",
                     list_name="sexes"),
            Question(name="preg", xlsform_type="text", label="X",
                     relevant=relevant)],
        choice_lists={"sexes": ChoiceList("sexes", [
            Choice("male", "Male"), Choice("female", "Female")])})


def test_dead_value_comparison_flagged():
    report = Validator(deep=False).validate(_sex_form("${sex}='femalee'"))
    assert any("never be true" in f.message for f in report.warnings)


def test_valid_value_comparison_not_flagged():
    report = Validator(deep=False).validate(_sex_form("${sex}='female'"))
    assert not any("never be true" in f.message for f in report.findings)


def test_selected_value_checked_too():
    qn = _sex_form("selected(${sex}, 'both')")
    report = Validator(deep=False).validate(qn)
    assert any("never be true" in f.message for f in report.warnings)


# --- expanded logic patterns -----------------------------------------------------
def _known():
    enrolled = Question(name="enrolled", raw_label="Are you enrolled?",
                        xlsform_type="select_one yes_no", source_number="1")
    age = Question(name="age_years", raw_label="Respondent age in years",
                   xlsform_type="integer", source_number="2")
    marital = Question(name="marital_status", raw_label="Marital status",
                       xlsform_type="select_one m", list_name="m",
                       raw_choices=["Single", "Married", "Divorced"],
                       source_number="3")
    return [enrolled, age, marital]


def _resolve(logic: str) -> str:
    known = _known()
    q = Question(raw_label="X", name="x", logic=logic)
    return LogicEngine().resolve(q, previous=known[-1], known=known + [q])


def test_unless_negates():
    assert _resolve("unless yes") == "not(${enrolled}='1')"


def test_only_if_prefix():
    assert _resolve("only if age over 18") == "${age_years}>18"


def test_if_not_negates():
    assert _resolve("if not yes") == "not(${enrolled}='1')"


def test_between_range():
    assert _resolve("if age between 18 and 65") == \
        "${age_years}>=18 and ${age_years}<=65"


def test_between_inside_compound():
    assert _resolve("if yes and age between 18 and 65") == \
        "${enrolled}='1' and ${age_years}>=18 and ${age_years}<=65"


def test_choice_value_shorthand():
    assert _resolve("if married") == "${marital_status}='married'"


def test_is_not_inequality():
    assert _resolve("if marital status is not single") == \
        "${marital_status}!='single'"


def test_question_number_reference():
    assert _resolve("if question 2 is over 60") == "${age_years}>60"
    assert _resolve("if q3 is divorced") == "${marital_status}='divorced'"


def test_answer_is_synonyms():
    assert _resolve("if the answer is yes") == "${enrolled}='1'"
    assert _resolve("if answered no") == "${enrolled}='0'"


def test_ambiguous_shorthand_stays_uncompiled():
    """Two selects offering the same value -> honestly refuse to guess."""
    known = _known()
    dup = Question(name="prev_marital", raw_label="Previous marital status",
                   xlsform_type="select_one p", list_name="p",
                   raw_choices=["Single", "Married"], source_number="4")
    q = Question(raw_label="X", name="x", logic="if married")
    got = LogicEngine().resolve(q, previous=dup, known=known + [dup, q])
    assert got == ""


# --- expanded constraints ----------------------------------------------------------
def _constraint(label: str, xtype: str) -> str:
    q = Question(raw_label=label, xlsform_type=xtype)
    ConstraintEngine().apply(q)
    return q.constraint


def test_count_nonnegative():
    assert _constraint("How many children do you have?", "integer") == ". >= 0"


def test_year_range():
    assert _constraint("Which year did you move here?", "integer") == \
        ". >= 1900 and . <= 2100"


def test_hours_per_day():
    assert _constraint("Hours per day spent farming", "integer") == \
        ". >= 0 and . <= 24"


def test_phone_and_email_regex_are_syntactically_valid():
    v = ExpressionValidator()
    for label in ("Phone number", "Email address"):
        c = _constraint(label, "text")
        assert c.startswith("regex(")
        err, _ = v.check(c)
        assert err is None, f"{label}: {err}"


def test_age_still_wins_over_count():
    """'age' template must take precedence over the generic count rule."""
    assert _constraint("Respondent age", "integer") == ". >= 0 and . <= 120"


# --- parser robustness ---------------------------------------------------------------
def test_coded_options_preserve_codes():
    qn = QuestionnaireParser().parse_text(
        "What is your marital status?\n1 = Single\n2 = Married\n97 = Refused\n")
    assert qn.questions[0].raw_choices == ["1=Single", "2=Married", "97=Refused"]
    result = Workflow().run(qn, form_title="T", form_id="t", write_outputs=False)
    cl = next(v for k, v in result.questionnaire.choice_lists.items() if k != "yes_no")
    assert [(c.name, c.label) for c in cl.choices] == \
        [("1", "Single"), ("2", "Married"), ("97", "Refused")]
    assert result.is_valid


def test_required_asterisk_detected_and_stripped():
    qn = QuestionnaireParser().parse_text("What is your full name? *\n")
    q = qn.questions[0]
    assert q.required is True
    assert not q.raw_label.endswith("*")


def test_required_tag_detected():
    qn = QuestionnaireParser().parse_text("District of residence (required)\n")
    q = qn.questions[0]
    assert q.required is True
    assert "(required)" not in q.raw_label.lower()


def test_colon_numbering_and_source_number():
    qn = QuestionnaireParser().parse_text(
        "1. Are you enrolled?\nYes\nNo\nQ2: Respondent age\n3) District name\n")
    numbers = [q.source_number for q in qn.questions]
    assert numbers == ["1", "2", "3"]
    labels = [q.raw_label for q in qn.questions]
    assert labels == ["Are you enrolled?", "Respondent age", "District name"]


def test_question_number_logic_end_to_end():
    """Numbered reference resolves through the whole pipeline."""
    text = ("1. Are you employed?\nYes\nNo\n"
            "2. Respondent age\n"
            "3. Occupation details\n"
            "If question 1 is yes, ask question 3.\n")
    result = Workflow().run(
        QuestionnaireParser().parse_text(text),
        form_title="T", form_id="t", write_outputs=False)
    occ = next(q for q in result.questionnaire.questions
              if q.name == "occupation_details")
    assert occ.relevant == "${employed}='1'"
    assert result.is_valid


# --- the high-confidence scenario: everything specified, everything compiled ---------
def test_fully_specified_questionnaire_compiles_completely():
    """A questionnaire written with clear skip logic, coded options and
    required markers must produce a fully-wired, valid form with no
    uncompiled logic left over."""
    text = (
        "SECTION A: SCREENING\n"
        "1. Are you a resident of this district? *\n"
        "Yes\n"
        "No\n"
        "2. How many years have you lived here?\n"
        "If question 1 is yes.\n"
        "3. Respondent age *\n"
        "SECTION B: DETAILS\n"
        "4. Marital status\n"
        "1 = Single\n"
        "2 = Married\n"
        "3 = Divorced\n"
        "5. Spouse name\n"
        "If question 4 is married.\n"
        "6. Which year did you marry?\n"
        "If married.\n"
    )
    result = Workflow().run(QuestionnaireParser().parse_text(text),
                            form_title="Residency Survey", form_id="res",
                            write_outputs=False)
    assert result.is_valid, [f.message for f in result.report.errors]
    by_name = {q.name: q for q in result.questionnaire.questions}

    # skip logic all compiled
    assert by_name["many_years_lived_here"].relevant == "${resident_district}='1'"
    assert by_name["spouse_name"].relevant == "${marital_status}='2'"
    assert by_name["year_marry"].relevant == "${marital_status}='2'"
    # required markers honoured
    assert by_name["resident_district"].required is True
    assert by_name["respondent_age"].required is True
    # constraints attached
    assert by_name["respondent_age"].constraint == ". >= 0 and . <= 120"
    assert by_name["year_marry"].constraint == ". >= 1900 and . <= 2100"
    # nothing left flagged as uncompiled
    uncompiled = [a for q in result.questionnaire.questions
                  for a in q.assumptions if "could not be auto-compiled" in a]
    assert uncompiled == []