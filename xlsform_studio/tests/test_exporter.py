"""Tests for the XLSForm builders and exporter."""

import openpyxl

from xlsform_studio.models import (Choice, ChoiceList, FormSettings,
                                      Question, Questionnaire)
from xlsform_studio.xlsform.choices_builder import ChoicesBuilder
from xlsform_studio.xlsform.exporter import XLSFormExporter
from xlsform_studio.xlsform.settings_builder import SettingsBuilder
from xlsform_studio.xlsform.survey_builder import SurveyBuilder


def _sample():
    qn = Questionnaire(
        settings=FormSettings(form_title="Demo Form"),
        questions=[
            Question(name="sex", xlsform_type="select_one sex", label="Sex", list_name="sex"),
            Question(name="age", xlsform_type="integer", label="Age", required=True),
        ],
        choice_lists={"sex": ChoiceList("sex", [Choice("1", "Male"), Choice("2", "Female")])},
    )
    return qn


def test_survey_rows():
    rows = SurveyBuilder().build(_sample())
    assert rows[0]["type"] == "select_one sex"
    assert rows[1]["required"] == "yes"


def test_choices_rows_only_referenced():
    rows = ChoicesBuilder().build(_sample())
    assert {r["label"] for r in rows} == {"Male", "Female"}


def test_settings_generates_id_and_version():
    row = SettingsBuilder().build(_sample())[0]
    assert row["form_id"] == "demo_form"
    assert row["version"]  # auto timestamp


def test_export_creates_three_sheets(tmp_path):
    path = XLSFormExporter().export(_sample(), tmp_path / "form.xlsx")
    wb = openpyxl.load_workbook(path)
    assert set(wb.sheetnames) == {"survey", "choices", "settings"}


def test_export_bytes_nonempty():
    data = XLSFormExporter().export_bytes(_sample())
    assert data[:2] == b"PK"  # xlsx is a zip


def test_group_rows_for_sections():
    qn = Questionnaire(questions=[
        Question(name="a", xlsform_type="integer", label="A", section="Demographics")])
    rows = SurveyBuilder().build(qn)
    assert rows[0]["type"] == "begin group"
    assert rows[-1]["type"] == "end group"
