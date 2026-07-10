"""End-to-end tests for the workflow controller (Iterations 1-6)."""

import json

import openpyxl

from xlsform_architect.app.workflow import Workflow


SAMPLE = {
    "settings": {"form_title": "OTP Register"},
    "category": "imam",
    "survey": [
        {"question": "Is the child currently enrolled in OTP?",
         "choices": ["Yes", "No"], "required": True},
        {"question": "Admission date", "logic": "ask if yes"},
        {"question": "Child age in months"},
        {"question": "MUAC (cm)"},
    ],
}


def test_run_from_dict_valid():
    result = Workflow().run_from_dict(SAMPLE, write_outputs=False)
    assert result.is_valid
    names = [q.name for q in result.questionnaire.questions]
    assert "child_enrolled_otp" in names
    assert "admission_date" in names


def test_relevant_compiled_end_to_end():
    result = Workflow().run_from_dict(SAMPLE, write_outputs=False)
    admission = next(q for q in result.questionnaire.questions
                     if q.name == "admission_date")
    assert admission.relevant == "${child_enrolled_otp}='1'"


def test_muac_classification_added():
    result = Workflow().run_from_dict(SAMPLE, write_outputs=False)
    names = [q.name for q in result.questionnaire.questions]
    assert "muac_class" in names


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
