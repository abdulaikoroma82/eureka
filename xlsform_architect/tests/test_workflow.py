"""End-to-end tests for the workflow controller."""

import json

import openpyxl

from xlsform_architect.app.workflow import Workflow


SAMPLE = {
    "settings": {"form_title": "Event Registration"},
    "survey": [
        {"question": "Are you attending the event?",
         "choices": ["Yes", "No"], "required": True},
        {"question": "Preferred session date", "logic": "ask if yes"},
        {"question": "Number of guests"},
        {"question": "Full name"},
    ],
}


def test_run_from_dict_valid():
    result = Workflow().run_from_dict(SAMPLE, write_outputs=False)
    assert result.is_valid
    names = [q.name for q in result.questionnaire.questions]
    assert "attending_event" in names
    assert "preferred_session_date" in names


def test_relevant_compiled_end_to_end():
    result = Workflow().run_from_dict(SAMPLE, write_outputs=False)
    dated = next(q for q in result.questionnaire.questions
                 if q.name == "preferred_session_date")
    assert dated.relevant == "${attending_event}='1'"


def test_types_inferred():
    result = Workflow().run_from_dict(SAMPLE, write_outputs=False)
    by_name = {q.name: q for q in result.questionnaire.questions}
    assert by_name["attending_event"].xlsform_type == "select_one yes_no"
    assert by_name["num_guests"].xlsform_type == "integer"
    assert by_name["full_name"].xlsform_type == "text"


def test_full_output_package_written(tmp_path):
    result = Workflow().run_from_dict(SAMPLE, output_dir=tmp_path)
    for key in ("xlsform", "data_dictionary", "validation_report",
                "assumption_log", "logic_map", "version_history"):
        assert key in result.outputs
        assert result.outputs[key].exists()


def test_xlsform_opens(tmp_path):
    result = Workflow().run_from_dict(SAMPLE, output_dir=tmp_path)
    wb = openpyxl.load_workbook(result.outputs["xlsform"])
    assert set(wb.sheetnames) == {"survey", "choices", "settings"}


def test_run_from_file_json(tmp_path):
    path = tmp_path / "form.json"
    path.write_text(json.dumps(SAMPLE), encoding="utf-8")
    result = Workflow().run_from_file(path, output_dir=tmp_path)
    assert result.is_valid


def test_version_history_appends(tmp_path):
    wf = Workflow()
    wf.run_from_dict(SAMPLE, output_dir=tmp_path)
    wf.run_from_dict(SAMPLE, output_dir=tmp_path)
    history = json.loads((tmp_path / "version_history.json").read_text())
    assert len(history) == 2


def test_progress_callback_invoked():
    seen = []
    Workflow().run_from_dict(SAMPLE, write_outputs=False,
                             progress=lambda step, status: seen.append((step, status)))
    assert any(status == "done" for _, status in seen)
