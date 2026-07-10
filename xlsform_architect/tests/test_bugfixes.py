"""Regression tests for bugs found during the platform upgrade."""

from xlsform_architect.app.workflow import Workflow
from xlsform_architect.models import Question, Questionnaire
from xlsform_architect.parsers.questionnaire_parser import QuestionnaireParser
from xlsform_architect.xlsform.survey_builder import SurveyBuilder


def test_explicit_select_list_name_materialised():
    """`type: select_one mylist` + choices must create the 'mylist' list."""
    data = {"settings": {"form_title": "T", "form_id": "t"}, "survey": [
        {"question": "Pick one", "type": "select_one mylist",
         "choices": ["A", "B"]}]}
    result = Workflow().run_from_dict(data, write_outputs=False)
    assert result.is_valid
    assert "mylist" in result.questionnaire.choice_lists
    assert len(result.questionnaire.choice_lists["mylist"].choices) == 2


def test_rank_choices_materialised():
    """rank questions draw items from the choices sheet like selects."""
    data = {"settings": {"form_title": "T", "form_id": "t"}, "survey": [
        {"question": "Rank these", "type": "rank prefs",
         "choices": ["First", "Second"]}]}
    result = Workflow().run_from_dict(data, target="odk", write_outputs=False)
    assert result.is_valid
    assert "prefs" in result.questionnaire.choice_lists


def test_duplicate_section_names_get_unique_groups():
    qn = Questionnaire(questions=[
        Question(name="a", xlsform_type="integer", label="A", section="Details"),
        Question(name="b", xlsform_type="integer", label="B", section="Other"),
        Question(name="c", xlsform_type="integer", label="C", section="Details"),
    ])
    rows = SurveyBuilder().build(qn)
    begin_names = [r["name"] for r in rows if r["type"] == "begin group"]
    assert len(begin_names) == len(set(begin_names)), begin_names


def test_inline_slash_three_options():
    qn = QuestionnaireParser().parse_text(
        "How satisfied are you?\nLow / Medium / High\n")
    assert qn.questions[0].raw_choices == ["Low", "Medium", "High"]


def test_imperative_with_slash_not_swallowed():
    qn = QuestionnaireParser().parse_text(
        "Are you registered?\nYes\nNo\nRecord height / weight\n")
    assert len(qn.questions) == 2
    assert qn.questions[0].raw_choices == ["Yes", "No"]


def test_multiword_base_type_for_text_audit():
    q = Question(xlsform_type="text audit")
    assert q.base_type == "text audit"


def test_txt_extension_supported():
    from xlsform_architect.app.config import SUPPORTED_INPUT_EXTENSIONS
    assert ".txt" in SUPPORTED_INPUT_EXTENSIONS
    assert ".md" in SUPPORTED_INPUT_EXTENSIONS
