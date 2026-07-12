"""Tests for the optional AI layer (DeepSeek), fully mocked - no network.

Every test replaces DeepSeekClient._post (or complete_json) with a canned
response, so these tests never make a real API call, never need an API key,
and run identically in CI as locally.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from xlsform_studio.ai.client import AIError, DeepSeekClient
from xlsform_studio.ai.config import AI_FEATURES, AIConfig
from xlsform_studio.ai.constraint_reviewer import AICrossFieldConstraintReviewer
from xlsform_studio.ai.finding_explainer import AIFindingExplainer
from xlsform_studio.ai.pipeline import AIPipeline
from xlsform_studio.ai.quality_reviewer import AIQualityReviewer
from xlsform_studio.ai.translator import AITranslator
from xlsform_studio.models import Choice, ChoiceList, FormSettings, Question, Questionnaire
from xlsform_studio.validation.report_generator import Finding, ValidationReport


def _client(reply: dict) -> DeepSeekClient:
    """A client whose complete_json always returns *reply*."""
    client = DeepSeekClient(api_key="test-key")
    client.complete_json = lambda *a, **kw: reply  # type: ignore[method-assign]
    return client


def _failing_client(message: str = "boom") -> DeepSeekClient:
    client = DeepSeekClient(api_key="test-key")

    def raise_error(*a, **kw):
        raise AIError(message)
    client.complete_json = raise_error  # type: ignore[method-assign]
    return client


# --- DeepSeekClient ---------------------------------------------------------
def test_client_unavailable_without_key():
    client = DeepSeekClient(api_key="")
    assert client.available is False
    with pytest.raises(AIError):
        client.complete_json("sys", "user")


def test_client_posts_and_parses_json():
    client = DeepSeekClient(api_key="k")
    fake_body = {"choices": [{"message": {"content": json.dumps({"ok": True})}}]}
    with patch.object(DeepSeekClient, "_post", return_value=fake_body) as mock_post:
        result = client.complete_json("system", "user prompt")
    assert result == {"ok": True}
    assert mock_post.call_args[0][0] == "/chat/completions"


def test_client_raises_on_malformed_json_content():
    client = DeepSeekClient(api_key="k")
    fake_body = {"choices": [{"message": {"content": "not json"}}]}
    with patch.object(DeepSeekClient, "_post", return_value=fake_body):
        with pytest.raises(AIError):
            client.complete_json("system", "user prompt")


def test_client_raises_on_unexpected_shape():
    client = DeepSeekClient(api_key="k")
    with patch.object(DeepSeekClient, "_post", return_value={"nope": True}):
        with pytest.raises(AIError):
            client.complete_json("system", "user prompt")


# --- AITranslator ------------------------------------------------------------
def test_translator_adds_extra_columns():
    qn = Questionnaire(
        settings=FormSettings(form_title="T"),
        questions=[Question(name="age", label="Age", xlsform_type="integer")])
    client = _client({"1": "Âge"})
    notes = AITranslator(client).translate(qn, [("French", "fr")])
    assert qn.questions[0].extra["label::French (fr)"] == "Âge"
    assert any("French" in n for n in notes)


def test_translator_includes_choice_labels():
    qn = Questionnaire(
        questions=[Question(name="sex", label="Sex", xlsform_type="select_one sex",
                            list_name="sex")],
        choice_lists={"sex": ChoiceList("sex", [Choice("m", "Male")])})
    client = _client({"1": "Sexe", "2": "Homme"})
    AITranslator(client).translate(qn, [("French", "fr")])
    assert qn.choice_lists["sex"].choices[0].extra["label::French (fr)"] == "Homme"


def test_translator_degrades_gracefully_on_error():
    qn = Questionnaire(questions=[Question(name="a", label="A", xlsform_type="text")])
    notes = AITranslator(_failing_client("network down")).translate(qn, [("French", "fr")])
    assert "extra" not in qn.questions[0].__dict__ or not qn.questions[0].extra
    assert any("Skipped French" in n for n in notes)


def test_translator_noop_with_no_languages():
    qn = Questionnaire(questions=[Question(name="a", label="A", xlsform_type="text")])
    notes = AITranslator(_client({})).translate(qn, [])
    assert notes == []


def test_translator_co_share_never_overwrites_user_supplied_translation():
    """A user-supplied translation is authoritative; AI must fill gaps only,
    never overwrite it - the co-share contract."""
    qn = Questionnaire(questions=[
        Question(name="a", label="Age", xlsform_type="integer",
                 extra={"label::French (fr)": "Âge (déjà traduit)"}),
        Question(name="b", label="Name", xlsform_type="text"),
    ])
    client = _client({"1": "Nom"})  # only ONE item should be sent (the gap)
    notes = AITranslator(client).translate(qn, [("French", "fr")])
    assert qn.questions[0].extra["label::French (fr)"] == "Âge (déjà traduit)"
    assert qn.questions[1].extra["label::French (fr)"] == "Nom"
    assert any("1/1" in n and "already supplied" in n for n in notes)


def test_translator_skips_api_call_when_nothing_missing():
    qn = Questionnaire(questions=[
        Question(name="a", label="Age", xlsform_type="integer",
                 extra={"label::French (fr)": "Âge"})])
    calls = []
    client = DeepSeekClient(api_key="k")
    client.complete_json = lambda *a, **kw: calls.append(1) or {}
    notes = AITranslator(client).translate(qn, [("French", "fr")])
    assert calls == []          # no API call made at all
    assert any("nothing to do" in n for n in notes)


def test_translator_per_language_independence():
    """Missing in French but already supplied in Spanish - independent."""
    qn = Questionnaire(questions=[
        Question(name="a", label="Age", xlsform_type="integer",
                 extra={"label::Spanish (es)": "Edad"})])
    client = _client({"1": "Âge"})
    AITranslator(client).translate(qn, [("French", "fr"), ("Spanish", "es")])
    assert qn.questions[0].extra["label::French (fr)"] == "Âge"
    assert qn.questions[0].extra["label::Spanish (es)"] == "Edad"  # untouched


# --- AIQualityReviewer --------------------------------------------------------
def test_reviewer_converts_findings():
    qn = Questionnaire(questions=[Question(name="age_months", label="Age in months",
                                           xlsform_type="integer", constraint=". <= 120")])
    reply = {"findings": [{"question_name": "age_months",
                           "issue": "Constraint looks like years, not months",
                           "explanation": "label says months but max is 120"}]}
    findings = AIQualityReviewer(_client(reply)).review(qn)
    assert len(findings) == 1
    assert findings[0].category == "ai_review"
    assert findings[0].level == "warning"       # always capped, never error
    assert "months" in findings[0].message


def test_reviewer_empty_findings_when_clean():
    qn = Questionnaire(questions=[Question(name="a", xlsform_type="integer")])
    findings = AIQualityReviewer(_client({"findings": []})).review(qn)
    assert findings == []


def test_reviewer_degrades_gracefully_on_error():
    qn = Questionnaire(questions=[Question(name="a", xlsform_type="integer")])
    findings = AIQualityReviewer(_failing_client()).review(qn)
    assert len(findings) == 1
    assert findings[0].level == "info"


def test_reviewer_asks_about_respondent_experience():
    """The broadened brief must reach the model: semantic, naming AND
    respondent-experience checks, grounded in the survey context."""
    qn = Questionnaire(questions=[Question(name="a", label="A",
                                           xlsform_type="integer")])
    captured = {}
    client = DeepSeekClient(api_key="k")

    def fake(system, user, **kw):
        captured["system"] = system
        captured["user"] = user
        return {"findings": []}
    client.complete_json = fake

    AIQualityReviewer(client).review(qn, survey_context="household survey")
    assert "RESPONDENT EXPERIENCE" in captured["system"]
    assert "household survey" in captured["user"]


# --- AICrossFieldConstraintReviewer ---------------------------------------------
def _questionnaire_with_date_pair():
    q1 = Question(name="start_date", label="Start date", xlsform_type="date")
    q2 = Question(name="end_date", label="End date", xlsform_type="date")
    return Questionnaire(questions=[q1, q2])


def test_cross_constraint_applied_when_valid():
    qn = _questionnaire_with_date_pair()
    reply = {"suggestions": [{"question_name": "end_date",
                              "constraint": ". >= ${start_date}",
                              "constraint_message": "End date must be on or after start date.",
                              "rationale": "end after start"}]}
    notes = AICrossFieldConstraintReviewer(_client(reply)).suggest(qn)
    assert qn.questions[1].constraint == ". >= ${start_date}"
    assert qn.questions[1].constraint_message == "End date must be on or after start date."
    assert any("Applied suggested" in n for n in notes)
    assert any("AI-suggested cross-field constraint" in a
              for a in qn.questions[1].assumptions)


def test_cross_constraint_rejects_self_reference():
    qn = _questionnaire_with_date_pair()
    reply = {"suggestions": [{"question_name": "end_date",
                              "constraint": ". >= ${end_date}"}]}
    notes = AICrossFieldConstraintReviewer(_client(reply)).suggest(qn)
    assert qn.questions[1].constraint == ""
    assert any("references itself" in n for n in notes)


def test_cross_constraint_rejects_non_cross_field():
    """A constraint with no ${...} reference isn't this feature's job."""
    qn = _questionnaire_with_date_pair()
    reply = {"suggestions": [{"question_name": "end_date", "constraint": ". <= today()"}]}
    notes = AICrossFieldConstraintReviewer(_client(reply)).suggest(qn)
    assert qn.questions[1].constraint == ""
    assert any("not a cross-field constraint" in n for n in notes)


def test_cross_constraint_rejects_unknown_field_reference():
    qn = _questionnaire_with_date_pair()
    reply = {"suggestions": [{"question_name": "end_date",
                              "constraint": ". >= ${ghost}"}]}
    notes = AICrossFieldConstraintReviewer(_client(reply)).suggest(qn)
    assert qn.questions[1].constraint == ""
    assert any("unknown field" in n for n in notes)


def test_cross_constraint_combines_with_existing_single_field_constraint():
    """The common real case: the deterministic engine already set a generic
    single-field constraint (e.g. 'not in the future'); the AI's cross-field
    addition must be COMBINED, not blocked, so both rules end up enforced."""
    qn = _questionnaire_with_date_pair()
    qn.questions[1].constraint = ". <= today()"
    qn.questions[1].constraint_message = "Date cannot be in the future."
    reply = {"suggestions": [{"question_name": "end_date",
                              "constraint": ". >= ${start_date}",
                              "constraint_message": "Must be after start date."}]}
    notes = AICrossFieldConstraintReviewer(_client(reply)).suggest(qn)
    assert qn.questions[1].constraint == "(. <= today()) and (. >= ${start_date})"
    assert "Must be after start date." in qn.questions[1].constraint_message
    assert "Date cannot be in the future." in qn.questions[1].constraint_message
    assert any("Combined suggested" in n for n in notes)


def test_cross_constraint_skips_when_reference_already_present():
    """Avoid combining a duplicate/conflicting reference to the same field."""
    qn = _questionnaire_with_date_pair()
    qn.questions[1].constraint = ". >= ${start_date} and . <= today()"
    reply = {"suggestions": [{"question_name": "end_date",
                              "constraint": ". >= ${start_date}"}]}
    notes = AICrossFieldConstraintReviewer(_client(reply)).suggest(qn)
    assert qn.questions[1].constraint == ". >= ${start_date} and . <= today()"
    assert any("avoid a conflict" in n for n in notes)


def test_cross_constraint_rejects_unknown_target():
    qn = _questionnaire_with_date_pair()
    reply = {"suggestions": [{"question_name": "nope", "constraint": ". >= ${start_date}"}]}
    notes = AICrossFieldConstraintReviewer(_client(reply)).suggest(qn)
    assert any("unknown question" in n for n in notes)


def test_cross_constraint_noop_on_empty_form():
    qn = Questionnaire()
    notes = AICrossFieldConstraintReviewer(_client({"suggestions": []})).suggest(qn)
    assert notes == []


def test_cross_constraint_degrades_gracefully_on_error():
    qn = _questionnaire_with_date_pair()
    notes = AICrossFieldConstraintReviewer(_failing_client("timeout")).suggest(qn)
    assert any("Skipped" in n for n in notes)
    assert qn.questions[1].constraint == ""


# --- AIFindingExplainer -----------------------------------------------------------
def test_explainer_adds_explanation_without_changing_the_finding():
    report = ValidationReport(findings=[
        Finding("error", "logic", "Select question 's' uses undefined list 'nolist'.", "s")])
    reply = {"explanations": [{"index": 0,
                               "explanation": "This question needs answer options defined."}]}
    notes = AIFindingExplainer(_client(reply)).explain(report)
    f = report.findings[0]
    assert f.explanation == "This question needs answer options defined."
    # The fact itself is untouched - rules remain sole authority.
    assert f.level == "error" and f.category == "logic"
    assert f.message == "Select question 's' uses undefined list 'nolist'."
    assert any("1/1" in n for n in notes)


def test_explainer_skips_info_level_and_ai_review_category():
    report = ValidationReport(findings=[
        Finding("info", "deployment", "Deep validation passed."),
        Finding("warning", "ai_review", "Already has its own explanation."),
        Finding("warning", "structure", "Form title is empty."),
    ])
    captured = {}
    client = DeepSeekClient(api_key="k")

    def fake(system, user, **kw):
        captured["user"] = user
        return {"explanations": [{"index": 2, "explanation": "Give the form a name."}]}
    client.complete_json = fake

    AIFindingExplainer(client).explain(report)
    assert report.findings[0].explanation == ""
    assert report.findings[1].explanation == ""
    assert report.findings[2].explanation == "Give the form a name."
    # Only the one eligible finding was sent to the model.
    assert '"index": 2' in captured["user"] or '"index":2' in captured["user"].replace(" ", "")


def test_explainer_noop_when_nothing_eligible():
    report = ValidationReport(findings=[Finding("info", "deployment", "All good.")])
    notes = AIFindingExplainer(_client({"explanations": []})).explain(report)
    assert notes == []


def test_explainer_does_not_reexplain_already_explained_finding():
    report = ValidationReport(findings=[
        Finding("error", "logic", "Broken.", explanation="Already explained.")])
    notes = AIFindingExplainer(_client({"explanations": []})).explain(report)
    assert notes == []
    assert report.findings[0].explanation == "Already explained."


def test_explainer_degrades_gracefully_on_error():
    report = ValidationReport(findings=[Finding("error", "logic", "Broken.")])
    notes = AIFindingExplainer(_failing_client()).explain(report)
    assert any("Skipped" in n for n in notes)
    assert report.findings[0].explanation == ""


# --- AIQualityReviewer naming/label clarity (advisory-only) ------------------------
def test_reviewer_can_flag_naming_clarity_as_advisory_only():
    qn = Questionnaire(questions=[
        Question(name="q7x", label="q7x", xlsform_type="text")])
    reply = {"findings": [{"question_name": "q7x",
                           "issue": "Variable name and label give no indication of content",
                           "explanation": "Consider a more descriptive name."}]}
    findings = AIQualityReviewer(_client(reply)).review(qn)
    assert len(findings) == 1
    assert findings[0].category == "ai_review"
    assert findings[0].level == "warning"       # advisory, never blocks
    # Crucially: the reviewer only RETURNS a finding, it never mutates name/label.
    assert qn.questions[0].name == "q7x"
    assert qn.questions[0].label == "q7x"


# --- AIPipeline orchestration --------------------------------------------------
def test_pipeline_noop_when_disabled():
    qn = Questionnaire(questions=[Question(name="a", xlsform_type="integer")])
    result_qn, notes, findings = AIPipeline(client=None).run(qn, AIConfig.disabled())
    assert notes == [] and findings == []
    assert result_qn is qn


def test_pipeline_noop_when_no_client_but_enabled():
    qn = Questionnaire(questions=[Question(name="a", xlsform_type="integer")])
    config = AIConfig(enabled=True, features=["translate"])
    _, notes, findings = AIPipeline(client=None).run(qn, config)
    assert findings == []
    assert any("no API key" in n or "DEEPSEEK_API_KEY" in n for n in notes)


def test_pipeline_runs_only_requested_features():
    """Only the enabled enrichment feature fires; others are left alone."""
    q1 = Question(name="start_date", label="Start date", xlsform_type="date")
    q2 = Question(name="end_date", label="End date", xlsform_type="date")
    qn = Questionnaire(questions=[q1, q2])
    config = AIConfig(enabled=True, features=["cross_constraints"])
    reply = {"suggestions": [{"question_name": "end_date",
                              "constraint": ". >= ${start_date}"}]}
    AIPipeline(client=_client(reply)).run(qn, config)
    assert qn.questions[1].constraint == ". >= ${start_date}"


def test_pipeline_default_features_include_cross_constraints():
    """A default AIConfig() must include the feature without any code needing
    to know about it explicitly - proves the wiring is data-driven."""
    assert "cross_constraints" in AI_FEATURES
    assert "cross_constraints" in AIConfig(enabled=True).features


def test_pipeline_review_receives_survey_context():
    qn = Questionnaire(questions=[Question(name="a", label="A",
                                           xlsform_type="integer")])
    config = AIConfig(enabled=True, features=["review"],
                      survey_context="market price monitoring")
    captured = {}
    client = DeepSeekClient(api_key="k")

    def fake(system, user, **kw):
        captured["user"] = user
        return {"findings": []}
    client.complete_json = fake

    AIPipeline(client=client).run(qn, config)
    assert "market price monitoring" in captured["user"]


def test_pipeline_runs_cross_constraints_feature():
    qn = _questionnaire_with_date_pair()
    config = AIConfig(enabled=True, features=["cross_constraints"])
    reply = {"suggestions": [{"question_name": "end_date",
                              "constraint": ". >= ${start_date}"}]}
    AIPipeline(client=_client(reply)).run(qn, config)
    assert qn.questions[1].constraint == ". >= ${start_date}"


def test_pipeline_explain_findings_runs_as_separate_post_validation_stage():
    report = ValidationReport(findings=[Finding("error", "structure", "No questions.")])
    reply = {"explanations": [{"index": 0, "explanation": "Add at least one question."}]}
    config = AIConfig(enabled=True, features=["explain_findings"])
    AIPipeline(client=_client(reply)).explain_findings(report, config)
    assert report.findings[0].explanation == "Add at least one question."


def test_pipeline_explain_findings_noop_when_not_requested():
    report = ValidationReport(findings=[Finding("error", "structure", "No questions.")])
    config = AIConfig(enabled=True, features=["translate"])  # explain not requested
    notes = AIPipeline(client=_client({"explanations": []})).explain_findings(report, config)
    assert notes == []
    assert report.findings[0].explanation == ""


def test_pipeline_unavailable_client_is_treated_as_no_key():
    qn = Questionnaire(questions=[Question(name="a", xlsform_type="integer")])
    config = AIConfig(enabled=True, features=["review"])
    unavailable = DeepSeekClient(api_key="")
    _, notes, findings = AIPipeline(client=unavailable).run(qn, config)
    assert findings == []
    assert any("skipped" in n.lower() for n in notes)


# --- End-to-end via Workflow ---------------------------------------------------
def test_workflow_default_unaffected_by_ai_package_import():
    """Importing/wiring the AI package must not change default behaviour."""
    from xlsform_studio.app.workflow import Workflow
    result = Workflow().run_from_dict(
        {"settings": {"form_title": "T", "form_id": "t"},
         "survey": [{"question": "Respondent age"}]},
        write_outputs=False)
    assert result.is_valid
    assert result.ai_ran is False


def test_workflow_with_ai_enabled_applies_translation():
    from xlsform_studio.app.workflow import Workflow
    client = _client({"1": "Âge du répondant"})
    config = AIConfig(enabled=True, features=["translate"],
                      translate_languages=[("French", "fr")],
                      translation_cache_path="")   # keep the test hermetic
    result = Workflow(ai_client=client).run_from_dict(
        {"settings": {"form_title": "T", "form_id": "t"},
         "survey": [{"question": "Respondent age"}]},
        ai_config=config, write_outputs=False)
    assert result.ai_ran is True
    q = result.questionnaire.questions[0]
    assert q.extra.get("label::French (fr)") == "Âge du répondant"
    # AI-added columns flow through to the exported bytes too.
    import io
    import openpyxl
    ws = openpyxl.load_workbook(io.BytesIO(result.xlsform_bytes))["survey"]
    assert "label::French (fr)" in [c.value for c in ws[1]]


def test_workflow_explains_findings_after_validation():
    """End-to-end: an actual validation error produced by the deterministic
    validator gets an AI explanation attached, proving the post-validation
    stage is really wired into Workflow._run (not just unit-testable in
    isolation)."""
    from xlsform_studio.app.workflow import Workflow

    reply = {"explanations": [{"index": 0,
                               "explanation": "Give your select question a list of answers."}]}
    config = AIConfig(enabled=True, features=["explain_findings"])
    result = Workflow(ai_client=_client(reply)).run_from_dict(
        {"settings": {"form_title": "T", "form_id": "t"},
         "survey": [{"question": "Pick one", "type": "select_one nolist"}]},
        ai_config=config, write_outputs=False)

    assert not result.is_valid  # the deterministic error is real and still blocks
    explained = [f for f in result.report.findings if f.explanation]
    assert explained and "answers" in explained[0].explanation
