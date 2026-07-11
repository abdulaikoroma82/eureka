"""Tests for the questionnaire parsers (Module 1)."""

import pandas as pd

from xlsform_studio.parsers.excel_parser import ExcelParser
from xlsform_studio.parsers.questionnaire_parser import QuestionnaireParser


# --- text parser (drives DOCX/PDF) -----------------------------------------
def test_text_parser_question_and_options():
    text = ("Are you a registered member?\n"
            "Yes\n"
            "No\n"
            "If yes, record membership date.")
    qn = QuestionnaireParser().parse_text(text)
    assert len(qn.questions) == 1
    q = qn.questions[0]
    assert q.raw_label.startswith("Are you")
    assert q.raw_choices == ["Yes", "No"]
    assert "membership date" in q.logic


def test_text_parser_sections():
    text = ("SECTION A: DEMOGRAPHICS\n"
            "What is the household size?\n"
            "SECTION B: FEEDBACK\n"
            "How would you rate the service?\n")
    qn = QuestionnaireParser().parse_text(text)
    sections = {q.section for q in qn.questions}
    assert any("Demographics" in s for s in sections)
    assert any("Feedback" in s for s in sections)


def test_text_parser_bulleted_options():
    text = ("What is your gender?\n"
            "- Male\n"
            "- Female\n")
    qn = QuestionnaireParser().parse_text(text)
    assert qn.questions[0].raw_choices == ["Male", "Female"]


def test_stacked_options_do_not_swallow_next_question():
    # "Number of guests" names a new topic and must not become an option
    # of the preceding Yes/No question.
    text = ("Are you attending?\n"
            "Yes\n"
            "No\n"
            "Number of guests\n")
    qn = QuestionnaireParser().parse_text(text)
    assert len(qn.questions) == 2
    assert qn.questions[0].raw_choices == ["Yes", "No"]
    assert qn.questions[1].raw_label == "Number of guests"


def test_imperative_prompt_becomes_question():
    text = "SECTION A: GPS\nRecord GPS location of the household\n"
    qn = QuestionnaireParser().parse_text(text)
    assert any("GPS location" in q.raw_label for q in qn.questions)


def test_slash_bulleted_option_split():
    text = "Gender\n- Male / Female\n"
    qn = QuestionnaireParser().parse_text(text)
    assert qn.questions[0].raw_choices == ["Male", "Female"]


# --- excel design grid ------------------------------------------------------
def test_excel_design_grid(tmp_path):
    df = pd.DataFrame([
        {"question": "Respondent age", "type": "integer", "required": "yes"},
        {"question": "Gender", "choices": "Male|Female"},
    ])
    path = tmp_path / "design.xlsx"
    df.to_excel(path, index=False)
    qn = ExcelParser().parse(path)
    assert len(qn.questions) == 2
    assert qn.questions[0].required is True
    assert qn.questions[1].raw_choices == ["Male", "Female"]


def test_excel_reads_existing_xlsform(tmp_path):
    survey = pd.DataFrame([
        {"type": "integer", "name": "age", "label": "Age"},
        {"type": "select_one sex", "name": "sex", "label": "Sex"},
    ])
    choices = pd.DataFrame([
        {"list_name": "sex", "name": "1", "label": "Male"},
        {"list_name": "sex", "name": "2", "label": "Female"},
    ])
    settings = pd.DataFrame([{"form_title": "Existing", "form_id": "existing", "version": "1"}])
    path = tmp_path / "form.xlsx"
    with pd.ExcelWriter(path) as writer:
        survey.to_excel(writer, sheet_name="survey", index=False)
        choices.to_excel(writer, sheet_name="choices", index=False)
        settings.to_excel(writer, sheet_name="settings", index=False)

    qn = ExcelParser().parse(path)
    assert qn.settings.form_title == "Existing"
    assert len(qn.questions) == 2
    assert "sex" in qn.choice_lists
    assert len(qn.choice_lists["sex"].choices) == 2


def test_csv_design_grid(tmp_path):
    path = tmp_path / "design.csv"
    path.write_text("question,type\nRespondent age,integer\n", encoding="utf-8")
    qn = ExcelParser().parse(path)
    assert qn.questions[0].raw_label == "Respondent age"
