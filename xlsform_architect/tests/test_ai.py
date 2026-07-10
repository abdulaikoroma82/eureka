"""Tests for the optional AI layer (DeepSeek), fully mocked - no network.

Every test replaces DeepSeekClient._post (or complete_json) with a canned
response, so these tests never make a real API call, never need an API key,
and run identically in CI as locally.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from xlsform_architect.ai.client import AIError, DeepSeekClient
from xlsform_architect.ai.config import AI_FEATURES, AIConfig
from xlsform_architect.ai.constraint_reviewer import AICrossFieldConstraintReviewer
from xlsform_architect.ai.pipeline import AIPipeline
from xlsform_architect.ai.quality_reviewer import AIQualityReviewer
from xlsform_architect.ai.skip_logic import AISkipLogicResolver
from xlsform_architect.ai.translator import AITranslator
from xlsform_architect.ai.type_classifier import AITypeClassifier
from xlsform_architect.models import Choice, ChoiceList, FormSettings, Question, Questionnaire


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


# --- AISkipLogicResolver -----------------------------------------------------
def _questionnaire_with_skip():
    q1 = Question(name="enrolled", label="Enrolled?", xlsform_type="select_one yes_no")
    q2 = Question(name="q20", label="Final notes", xlsform_type="text",
                 logic="if no, skip to question 20")
    q2.add_assumption("Skip pattern detected ('if no, skip to question 20'). "
                      "XLSForm expresses skips as 'relevant' conditions...")
    return Questionnaire(questions=[q1, q2])


def test_skip_logic_applies_valid_suggestion():
    qn = _questionnaire_with_skip()
    reply = {"suggestions": [{"question_name": "q20",
                              "relevant": "${enrolled}='1'",
                              "rationale": "shown only if enrolled"}]}
    notes = AISkipLogicResolver(_client(reply)).resolve(qn)
    assert qn.questions[1].relevant == "${enrolled}='1'"
    assert any("Applied suggested relevant" in n for n in notes)
    assert any("AI-suggested" in a for a in qn.questions[1].assumptions)


def test_skip_logic_rejects_unknown_reference():
    qn = _questionnaire_with_skip()
    reply = {"suggestions": [{"question_name": "q20",
                              "relevant": "${ghost_field}='1'"}]}
    AISkipLogicResolver(_client(reply)).resolve(qn)
    assert qn.questions[1].relevant == ""


def test_skip_logic_rejects_unknown_target_question():
    qn = _questionnaire_with_skip()
    reply = {"suggestions": [{"question_name": "does_not_exist",
                              "relevant": "${enrolled}='1'"}]}
    notes = AISkipLogicResolver(_client(reply)).resolve(qn)
    assert any("unknown question" in n for n in notes)


def test_skip_logic_does_not_overwrite_existing_relevant():
    qn = _questionnaire_with_skip()
    qn.questions[1].relevant = "${enrolled}='0'"
    reply = {"suggestions": [{"question_name": "q20", "relevant": "${enrolled}='1'"}]}
    AISkipLogicResolver(_client(reply)).resolve(qn)
    assert qn.questions[1].relevant == "${enrolled}='0'"


def test_skip_logic_noop_when_nothing_pending():
    qn = Questionnaire(questions=[Question(name="a", xlsform_type="text")])
    notes = AISkipLogicResolver(_client({"suggestions": []})).resolve(qn)
    assert notes == []


def test_logic_fallback_also_handles_unparseable_condition_on_same_question():
    """The broadened resolver must also catch generic compile failures, not
    just 'skip to' phrasing, and can target the SAME question."""
    q1 = Question(name="hh_size", label="Household size", xlsform_type="integer")
    q2 = Question(name="crowding", label="Crowding index", xlsform_type="text",
                 logic="only if household has more than 3 members and a child under 5")
    q2.add_assumption("Logic 'only if household has more than 3 members and "
                      "a child under 5' could not be auto-compiled; please "
                      "review the relevant column.")
    qn = Questionnaire(questions=[q1, q2])
    reply = {"suggestions": [{"question_name": "crowding",
                              "relevant": "${hh_size}>3",
                              "rationale": "same-question complex condition"}]}
    notes = AISkipLogicResolver(_client(reply)).resolve(qn)
    assert qn.questions[1].relevant == "${hh_size}>3"
    assert any("Applied suggested relevant" in n for n in notes)


def test_logic_fallback_request_includes_both_kinds():
    """Both a skip and an unparseable condition in the same form are batched
    into a single request."""
    q1 = Question(name="enrolled", xlsform_type="select_one yes_no")
    q2 = Question(name="notes", xlsform_type="text", logic="if no, skip to question 20")
    q2.add_assumption("Skip pattern detected ('if no, skip to question 20').")
    q3 = Question(name="crowding", xlsform_type="text", logic="complex phrase")
    q3.add_assumption("Logic 'complex phrase' could not be auto-compiled; "
                      "please review the relevant column.")
    qn = Questionnaire(questions=[q1, q2, q3])

    captured = {}
    client = DeepSeekClient(api_key="k")

    def fake_complete(system, user, **kw):
        captured["user"] = user
        return {"suggestions": []}
    client.complete_json = fake_complete

    AISkipLogicResolver(client).resolve(qn)
    compact = captured["user"].replace(" ", "")
    assert '"kind":"skip"' in compact
    assert '"kind":"condition"' in compact


# --- AITypeClassifier ---------------------------------------------------------
def _questionnaire_with_fallback():
    q = Question(name="misc", label="Preferred appointment slot", xlsform_type="text")
    q.add_assumption("No rule matched; defaulted to 'text'.")
    return Questionnaire(questions=[q])


def test_classifier_applies_recognised_type():
    qn = _questionnaire_with_fallback()
    reply = {"classifications": [{"name": "misc", "type": "time", "confidence": "high"}]}
    notes = AITypeClassifier(_client(reply)).classify(qn)
    assert qn.questions[0].xlsform_type == "time"
    assert any("misc" in n for n in notes)


def test_classifier_rejects_unrecognised_type():
    qn = _questionnaire_with_fallback()
    reply = {"classifications": [{"name": "misc", "type": "select_one", "confidence": "low"}]}
    AITypeClassifier(_client(reply)).classify(qn)
    assert qn.questions[0].xlsform_type == "text"


def test_classifier_leaves_text_when_ai_agrees():
    qn = _questionnaire_with_fallback()
    reply = {"classifications": [{"name": "misc", "type": "text", "confidence": "high"}]}
    AITypeClassifier(_client(reply)).classify(qn)
    assert qn.questions[0].xlsform_type == "text"


def test_classifier_reapplies_constraints_for_new_type():
    q = Question(name="age_q", raw_label="Respondent age", label="Respondent age",
                xlsform_type="text")
    q.add_assumption("No rule matched; defaulted to 'text'.")
    qn = Questionnaire(questions=[q])
    reply = {"classifications": [{"name": "age_q", "type": "integer", "confidence": "high"}]}
    AITypeClassifier(_client(reply)).classify(qn)
    assert qn.questions[0].constraint  # age constraint template applied


def test_classifier_noop_when_no_fallback_questions():
    qn = Questionnaire(questions=[Question(name="a", xlsform_type="integer")])
    notes = AITypeClassifier(_client({"classifications": []})).classify(qn)
    assert notes == []


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
    qn = _questionnaire_with_fallback()
    config = AIConfig(enabled=True, features=["classify"])
    reply = {"classifications": [{"name": "misc", "type": "time", "confidence": "high"}]}
    AIPipeline(client=_client(reply)).run(qn, config)
    assert qn.questions[0].xlsform_type == "time"


def test_pipeline_default_features_include_cross_constraints():
    """A default AIConfig() must include the new feature without any code
    needing to know about it explicitly - proves the wiring is data-driven."""
    assert "cross_constraints" in AI_FEATURES
    assert "cross_constraints" in AIConfig(enabled=True).features


def test_pipeline_runs_cross_constraints_feature():
    qn = _questionnaire_with_date_pair()
    config = AIConfig(enabled=True, features=["cross_constraints"])
    reply = {"suggestions": [{"question_name": "end_date",
                              "constraint": ". >= ${start_date}"}]}
    AIPipeline(client=_client(reply)).run(qn, config)
    assert qn.questions[1].constraint == ". >= ${start_date}"


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
    from xlsform_architect.app.workflow import Workflow
    result = Workflow().run_from_dict(
        {"settings": {"form_title": "T", "form_id": "t"},
         "survey": [{"question": "Respondent age"}]},
        write_outputs=False)
    assert result.is_valid
    assert result.ai_ran is False


def test_workflow_with_ai_enabled_applies_translation():
    from xlsform_architect.app.workflow import Workflow
    client = _client({"1": "Âge du répondant"})
    config = AIConfig(enabled=True, features=["translate"],
                      translate_languages=[("French", "fr")])
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
