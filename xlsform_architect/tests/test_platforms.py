"""Tests for platform-specific standards (Kobo / SurveyCTO / ODK)."""

import io

import openpyxl

from xlsform_architect.app.workflow import Workflow
from xlsform_architect.models import FormSettings, Question, Questionnaire
from xlsform_architect.validation.platform_validator import PlatformValidator
from xlsform_architect.validation.validator import Validator
from xlsform_architect.xlsform.exporter import XLSFormExporter


def _form(*questions):
    return Questionnaire(settings=FormSettings(form_title="T", form_id="t"),
                         questions=list(questions))


# --- per-platform type support ----------------------------------------------
def test_surveycto_rejects_rank():
    qn = _form(Question(name="r", xlsform_type="rank items", label="R"))
    findings = PlatformValidator().validate(qn, "surveycto")
    errors = [f for f in findings if f.level == "error"]
    assert errors and "not supported by SurveyCTO" in errors[0].message
    # The hint names the platforms that DO support it.
    assert "ODK" in errors[0].message


def test_odk_accepts_rank():
    qn = _form(Question(name="r", xlsform_type="rank items", label="R"))
    findings = PlatformValidator().validate(qn, "odk")
    assert not [f for f in findings if f.level == "error"]


def test_kobo_rejects_text_audit():
    qn = _form(Question(name="ta", xlsform_type="text audit", label=""))
    findings = PlatformValidator().validate(qn, "kobo")
    assert any(f.level == "error" and "not supported by KoboToolbox" in f.message
               for f in findings)


def test_surveycto_accepts_text_audit():
    qn = _form(Question(name="ta", xlsform_type="text audit", label=""))
    findings = PlatformValidator().validate(qn, "surveycto")
    assert not [f for f in findings if f.level == "error"]


# --- platform naming standards -----------------------------------------------
def test_surveycto_name_must_start_with_letter():
    qn = _form(Question(name="_hidden", xlsform_type="text", label="X"))
    findings = PlatformValidator().validate(qn, "surveycto")
    assert any("start with a letter" in f.message for f in findings)
    # ODK allows a leading underscore.
    assert not [f for f in PlatformValidator().validate(qn, "odk")
                if f.level == "error"]


def test_surveycto_32_char_stata_warning():
    long_name = "a" * 40
    qn = _form(Question(name=long_name, xlsform_type="text", label="X"))
    findings = PlatformValidator().validate(qn, "surveycto")
    assert any(f.level == "warning" and "32" in f.message for f in findings)


# --- honest per-platform compatibility matrix ---------------------------------
def test_matrix_is_per_platform():
    data = {"settings": {"form_title": "T", "form_id": "t"}, "survey": [
        {"question": "Rank preferences", "type": "rank prefs",
         "choices": ["A", "B"]}]}
    result = Workflow().run_from_dict(data, target="odk", write_outputs=False)
    assert result.report.compatibility["odk"] is True
    assert result.report.compatibility["kobo"] is True
    assert result.report.compatibility["surveycto"] is False


def test_target_errors_fail_validation():
    data = {"settings": {"form_title": "T", "form_id": "t"}, "survey": [
        {"question": "Rank preferences", "type": "rank prefs",
         "choices": ["A", "B"]}]}
    result = Workflow().run_from_dict(data, target="surveycto",
                                      write_outputs=False)
    assert not result.is_valid


# --- dialect export ------------------------------------------------------------
def _headers(xls_bytes: bytes):
    ws = openpyxl.load_workbook(io.BytesIO(xls_bytes))["survey"]
    return [c.value for c in ws[1]]


def test_surveycto_dialect_headers():
    qn = _form(Question(name="a", xlsform_type="integer", label="A"))
    headers = _headers(XLSFormExporter().export_bytes(qn, target="surveycto"))
    assert "relevance" in headers
    assert "constraint message" in headers
    assert "relevant" not in headers
    assert "constraint_message" not in headers


def test_standard_headers_for_kobo_and_default():
    qn = _form(Question(name="a", xlsform_type="integer", label="A"))
    for target in (None, "kobo", "odk"):
        headers = _headers(XLSFormExporter().export_bytes(qn, target=target))
        assert "relevant" in headers
        assert "relevance" not in headers


# --- workflow threading ---------------------------------------------------------
def test_workflow_records_target(tmp_path):
    data = {"settings": {"form_title": "T"}, "survey": [{"question": "Age"}]}
    result = Workflow().run_from_dict(data, target="surveycto",
                                      output_dir=tmp_path)
    assert result.target == "surveycto"
    assert result.report.target == "surveycto"
    import json
    history = json.loads((tmp_path / "version_history.json").read_text())
    assert history[-1]["target"] == "surveycto"


def test_validator_without_target_has_no_platform_findings():
    qn = _form(Question(name="a", xlsform_type="integer", label="A"))
    report = Validator(deep=False).validate(qn)
    assert not [f for f in report.findings if f.category == "platform"]


# --- Ona & CommCare -------------------------------------------------------------
def test_five_platforms_loaded():
    from xlsform_architect.engine.knowledge_base import KnowledgeBase
    names = set(KnowledgeBase.load().platform_names())
    assert {"kobo", "surveycto", "odk", "ona", "commcare"} <= names


def test_ona_accepts_osm_and_rank():
    qn = _form(Question(name="r", xlsform_type="rank items", label="R"),
               Question(name="m", xlsform_type="osm", label="M"))
    findings = PlatformValidator().validate(qn, "ona")
    assert not [f for f in findings if f.level == "error"]


def test_commcare_rejects_geotrace_and_rank():
    qn = _form(Question(name="t", xlsform_type="geotrace", label="T"),
               Question(name="r", xlsform_type="rank items", label="R"))
    findings = PlatformValidator().validate(qn, "commcare")
    errors = [f for f in findings if f.level == "error"]
    assert len(errors) == 2
    assert all("not supported by CommCare" in f.message for f in errors)


def test_commcare_accepts_core_types():
    qn = _form(Question(name="a", xlsform_type="integer", label="A"),
               Question(name="g", xlsform_type="geopoint", label="G"))
    findings = PlatformValidator().validate(qn, "commcare")
    assert not [f for f in findings if f.level == "error"]


def test_matrix_includes_new_platforms():
    qn = _form(Question(name="t", xlsform_type="geotrace", label="T"))
    matrix = PlatformValidator().matrix(qn, generally_valid=True)
    assert matrix["commcare"] is False    # no geotrace on CommCare
    assert matrix["odk"] is True
    assert matrix["ona"] is True


def test_workflow_accepts_commcare_target():
    data = {"settings": {"form_title": "T", "form_id": "t"},
            "survey": [{"question": "Age"}]}
    result = Workflow().run_from_dict(data, target="commcare",
                                      write_outputs=False)
    assert result.is_valid
    assert result.report.compatibility["commcare"] is True
