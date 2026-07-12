"""Tests for the advisory AI features (grouping, rewording, choice ordering,
naming), the shared AI-output validators, translation caching, logic-fallback
confidence scores, and the accept/apply flow. Fully mocked - no network."""

from __future__ import annotations

import json

from xlsform_studio.ai.choice_ordering import AIChoiceOrderingSuggester
from xlsform_studio.ai.client import AIError, DeepSeekClient
from xlsform_studio.ai.config import (AI_FEATURES, AIConfig,
                                         normalize_features)
from xlsform_studio.ai.grouping import AIGroupingSuggester
from xlsform_studio.ai.naming import AINamingSuggester
from xlsform_studio.ai.pipeline import AIPipeline
from xlsform_studio.ai.rewording import AIRewordingSuggester
from xlsform_studio.ai.suggestions import AISuggestion, apply_suggestions
from xlsform_studio.ai.translator import AITranslator
from xlsform_studio.models import (Choice, ChoiceList, FormSettings,
                                      Question, Questionnaire)
from xlsform_studio.validation import ai_validators
from xlsform_studio.validation.report_generator import (Finding,
                                                           ReportGenerator,
                                                           ValidationReport)


def _client(reply: dict) -> DeepSeekClient:
    client = DeepSeekClient(api_key="test-key")
    client.complete_json = lambda *a, **kw: reply  # type: ignore[method-assign]
    return client


def _counting_client(reply: dict):
    """Client that counts API calls and captures the last prompts."""
    client = DeepSeekClient(api_key="test-key")
    calls = []

    def fake(system, user, **kw):
        calls.append({"system": system, "user": user})
        return reply
    client.complete_json = fake
    return client, calls


def _failing_client(message: str = "boom") -> DeepSeekClient:
    client = DeepSeekClient(api_key="test-key")

    def raise_error(*a, **kw):
        raise AIError(message)
    client.complete_json = raise_error  # type: ignore[method-assign]
    return client


def _form() -> Questionnaire:
    return Questionnaire(
        settings=FormSettings(form_title="T", form_id="t"),
        questions=[
            Question(name="resident", label="Are you a resident?",
                     xlsform_type="select_one yes_no", list_name="yes_no"),
            Question(name="age", label="Respondent age",
                     xlsform_type="integer",
                     relevant="${resident}='1'"),
            Question(name="occupation", label="Main occupation",
                     xlsform_type="select_one occ", list_name="occ"),
        ],
        choice_lists={
            "yes_no": ChoiceList("yes_no", [Choice("1", "Yes"),
                                            Choice("0", "No")]),
            "occ": ChoiceList("occ", [
                Choice("other", "Other"), Choice("farm", "Farming"),
                Choice("fish", "Fishing"), Choice("trade", "Trading")]),
        })


# --- ai_validators ------------------------------------------------------------
def test_covers_exactly_once_ok():
    assert ai_validators.check_covers_exactly_once([[0, 1], [2]], 3) is None


def test_covers_missing_and_duplicated():
    assert "not assigned" in ai_validators.check_covers_exactly_once([[0]], 2)
    assert "more than once" in ai_validators.check_covers_exactly_once(
        [[0, 1], [1]], 2)
    assert "out of range" in ai_validators.check_covers_exactly_once([[0, 5]], 2)


def test_permutation_check():
    assert ai_validators.check_permutation(["a", "b"], ["b", "a"]) is None
    assert "missing" in ai_validators.check_permutation(["a", "b"], ["a", "a"])


def test_unique_nonempty():
    assert ai_validators.check_unique_nonempty(["A", "B"]) is None
    assert "duplicate" in ai_validators.check_unique_nonempty(["A", "A"])
    assert "empty" in ai_validators.check_unique_nonempty(["A", " "])


def test_check_expression():
    assert ai_validators.check_expression("${a} > 1", {"a"}) is None
    assert "unknown field" in ai_validators.check_expression("${b} > 1", {"a"})
    assert "syntax" in ai_validators.check_expression(". >< 1", {"a"})


def test_placeholders_preserved():
    assert ai_validators.check_placeholders_preserved(
        "Age of ${name}?", "How old is ${name}?") is None
    assert "drops" in ai_validators.check_placeholders_preserved(
        "Age of ${name}?", "How old are you?")
    assert "introduces" in ai_validators.check_placeholders_preserved(
        "Your age?", "Age of ${name}?")


def test_variable_name_rules():
    assert ai_validators.check_variable_name("age_years", set()) is None
    assert ai_validators.check_variable_name("1age", set()) is not None
    assert ai_validators.check_variable_name("has space", set()) is not None
    assert "collides" in ai_validators.check_variable_name("age", {"age"})
    assert "limit" in ai_validators.check_variable_name("x" * 41, set())


def test_clamp_advisory_level():
    assert ai_validators.clamp_advisory_level("info") == "info"
    assert ai_validators.clamp_advisory_level("error") == "warning"


# --- grouping -------------------------------------------------------------------
def test_grouping_produces_validated_suggestion():
    qn = _form()
    reply = {"sections": [
        {"name": "Screening", "question_indices": [0, 1]},
        {"name": "Livelihood", "question_indices": [2]}]}
    client, calls = _counting_client(reply)
    notes, suggestions = AIGroupingSuggester(client).suggest(qn)
    assert len(calls) == 1                       # one API call per form
    assert len(suggestions) == 1
    sug = suggestions[0]
    assert sug.kind == "grouping"
    assert sug.payload["sections"][0] == {"name": "Screening",
                                          "questions": ["resident", "age"]}
    # advisory: the form itself is untouched
    assert all(q.section == "" for q in qn.questions)


def test_grouping_rejects_incomplete_coverage():
    reply = {"sections": [{"name": "Only", "question_indices": [0]}]}
    notes, suggestions = AIGroupingSuggester(_client(reply)).suggest(_form())
    assert suggestions == []
    assert any("Rejected" in n for n in notes)


def test_grouping_rejects_duplicate_section_names():
    reply = {"sections": [
        {"name": "A", "question_indices": [0, 1]},
        {"name": "A", "question_indices": [2]}]}
    notes, suggestions = AIGroupingSuggester(_client(reply)).suggest(_form())
    assert suggestions == []
    assert any("duplicate" in n for n in notes)


def test_grouping_skips_forms_with_explicit_structure():
    qn = _form()
    qn.questions.insert(0, Question(name="g", xlsform_type="begin group"))
    client, calls = _counting_client({"sections": []})
    notes, suggestions = AIGroupingSuggester(client).suggest(qn)
    assert calls == []                           # not even an API call
    assert suggestions == []
    assert any("explicit groups" in n for n in notes)


def test_grouping_apply_assigns_sections():
    qn = _form()
    sug = AISuggestion(kind="grouping", target="", original="", suggested="",
                       payload={"sections": [
                           {"name": "Screening", "questions": ["resident", "age"]},
                           {"name": "Livelihood", "questions": ["occupation"]}]})
    notes = apply_suggestions(qn, [sug])
    assert sug.applied
    assert [q.section for q in qn.questions] == \
        ["Screening", "Screening", "Livelihood"]
    assert any("Applied accepted grouping" in n for n in notes)


def test_grouping_apply_refuses_reordering():
    qn = _form()
    sug = AISuggestion(kind="grouping", target="", original="", suggested="",
                       payload={"sections": [
                           {"name": "B", "questions": ["occupation", "age"]},
                           {"name": "A", "questions": ["resident"]}]})
    notes = apply_suggestions(qn, [sug])
    assert not sug.applied
    assert any("reorder" in n for n in notes)
    assert all(q.section == "" for q in qn.questions)


# --- rewording -------------------------------------------------------------------
def test_rewording_produces_suggestion_without_mutating():
    qn = _form()
    reply = {"suggestions": [{
        "question_name": "occupation",
        "label": "What is your main occupation?",
        "hint": "Select one.", "reason": "fragment, not a question"}]}
    notes, suggestions = AIRewordingSuggester(_client(reply)).suggest(qn)
    assert len(suggestions) == 1
    assert qn.questions[2].label == "Main occupation"    # untouched


def test_rewording_rejects_placeholder_loss():
    qn = Questionnaire(questions=[
        Question(name="c", label="Is ${name} enrolled?", xlsform_type="text")])
    reply = {"suggestions": [{"question_name": "c",
                              "label": "Is the child enrolled?"}]}
    notes, suggestions = AIRewordingSuggester(_client(reply)).suggest(qn)
    assert suggestions == []
    assert any("placeholder" in n for n in notes)


def test_rewording_split_is_display_only():
    qn = Questionnaire(questions=[
        Question(name="pr", label="Do you own a phone and a radio?",
                 xlsform_type="select_one yes_no")])
    reply = {"suggestions": [{"question_name": "pr",
                              "split_into": ["Do you own a phone?",
                                             "Do you own a radio?"],
                              "reason": "double-barreled"}]}
    notes, suggestions = AIRewordingSuggester(_client(reply)).suggest(qn)
    assert len(suggestions) == 1
    sug = suggestions[0]
    assert sug.kind == "split" and not sug.appliable
    # attempting to apply it anyway is refused, not half-done
    apply_notes = apply_suggestions(qn, [sug])
    assert not sug.applied
    assert any("advisory-only" in n for n in apply_notes)
    assert len(qn.questions) == 1


def test_rewording_apply_sets_label_and_keeps_author_hint():
    qn = _form()
    qn.questions[2].hint = "Author's own hint."
    sug = AISuggestion(kind="rewording", target="occupation",
                       original="Main occupation",
                       suggested="What is your main occupation?",
                       payload={"label": "What is your main occupation?",
                                "hint": "AI hint"})
    apply_suggestions(qn, [sug])
    assert qn.questions[2].label == "What is your main occupation?"
    assert qn.questions[2].hint == "Author's own hint."    # never overwritten
    assert any("AI-suggested rewording accepted" in a
              for a in qn.questions[2].assumptions)


# --- choice ordering -----------------------------------------------------------
def test_choice_order_produces_validated_suggestion():
    qn = _form()
    reply = {"orders": [{"list_name": "occ",
                         "order": ["farm", "fish", "trade", "other"],
                         "reason": "common answers first, Other last"}]}
    client, calls = _counting_client(reply)
    notes, suggestions = AIChoiceOrderingSuggester(client).suggest(qn)
    assert len(calls) == 1
    assert len(suggestions) == 1
    # advisory: list untouched until accepted
    assert qn.choice_lists["occ"].choice_names() == \
        ["other", "farm", "fish", "trade"]
    # yes_no was never offered to the model
    assert "yes_no" not in calls[0]["user"]


def test_choice_order_rejects_non_permutation():
    qn = _form()
    for bad in (["farm", "fish", "trade"],                    # dropped one
                ["farm", "fish", "trade", "other", "new"],    # invented one
                ["farm", "farm", "trade", "other"]):          # duplicated
        reply = {"orders": [{"list_name": "occ", "order": bad}]}
        notes, suggestions = AIChoiceOrderingSuggester(_client(reply)).suggest(qn)
        assert suggestions == []
        assert any("not a permutation" in n for n in notes)


def test_choice_order_apply_reorders_list():
    qn = _form()
    sug = AISuggestion(kind="choice_order", target="occ",
                       original="", suggested="",
                       payload={"order": ["farm", "fish", "trade", "other"]})
    apply_suggestions(qn, [sug])
    assert qn.choice_lists["occ"].choice_names() == \
        ["farm", "fish", "trade", "other"]
    assert any("reordering" in a for a in qn.questions[2].assumptions)


# --- naming ---------------------------------------------------------------------
def test_naming_produces_suggestion_deterministic_name_stays():
    qn = _form()
    reply = {"suggestions": [{"question_name": "occupation",
                              "suggested_name": "main_occupation",
                              "reason": "matches the label"}]}
    notes, suggestions = AINamingSuggester(_client(reply)).suggest(qn)
    assert len(suggestions) == 1
    assert qn.questions[2].name == "occupation"   # deterministic name in use


def test_naming_rejects_invalid_and_colliding_names():
    qn = _form()
    reply = {"suggestions": [
        {"question_name": "occupation", "suggested_name": "1bad"},
        {"question_name": "occupation", "suggested_name": "age"}]}
    notes, suggestions = AINamingSuggester(_client(reply)).suggest(qn)
    assert suggestions == []
    assert sum("Rejected" in n for n in notes) == 2


def test_naming_apply_renames_and_rewrites_references():
    qn = _form()
    sug = AISuggestion(kind="naming", target="resident",
                       original="resident", suggested="is_resident",
                       payload={"name": "is_resident"})
    apply_suggestions(qn, [sug])
    assert qn.questions[0].name == "is_resident"
    # the ${resident} reference in question 2's relevant followed the rename
    assert qn.questions[1].relevant == "${is_resident}='1'"


# --- translation cache ------------------------------------------------------------
def _translatable() -> Questionnaire:
    return Questionnaire(questions=[
        Question(name="age", label="Age", xlsform_type="integer")])


def test_translation_cache_round_trip(tmp_path):
    cache = tmp_path / "cache.json"
    qn1 = _translatable()
    client, calls = _counting_client({"1": "Âge"})
    AITranslator(client, cache_path=cache).translate(qn1, [("French", "fr")])
    assert len(calls) == 1
    data = json.loads(cache.read_text(encoding="utf-8"))
    entry = next(iter(data.values()))
    assert entry["translation"] == "Âge" and entry["timestamp"]

    # Second run: served entirely from cache, zero API calls.
    qn2 = _translatable()
    notes = AITranslator(client, cache_path=cache).translate(
        qn2, [("French", "fr")])
    assert len(calls) == 1                       # unchanged
    assert qn2.questions[0].extra["label::French (fr)"] == "Âge"
    assert any("translation cache" in n for n in notes)


def test_translation_cache_corrupt_file_falls_back_to_api(tmp_path):
    cache = tmp_path / "cache.json"
    cache.write_text("{not json", encoding="utf-8")
    qn = _translatable()
    client, calls = _counting_client({"1": "Âge"})
    AITranslator(client, cache_path=cache).translate(qn, [("French", "fr")])
    assert len(calls) == 1
    assert qn.questions[0].extra["label::French (fr)"] == "Âge"


def test_translation_cache_disabled_by_default_on_direct_construction(tmp_path,
                                                                       monkeypatch):
    monkeypatch.chdir(tmp_path)
    qn = _translatable()
    AITranslator(_client({"1": "Âge"})).translate(qn, [("French", "fr")])
    assert not list(tmp_path.iterdir())          # nothing written anywhere


# --- config / feature keys ----------------------------------------------------------
def test_new_features_registered():
    for feature in ("group", "rewrite", "order", "naming"):
        assert feature in AI_FEATURES
        assert feature in AIConfig(enabled=True).features


def test_feature_aliases_normalize():
    assert normalize_features(["explain", "cross", "group"]) == \
        ["explain_findings", "cross_constraints", "group"]


# --- pipeline orchestration -----------------------------------------------------------
def test_pipeline_collects_suggestions_without_mutating():
    qn = _form()
    config = AIConfig(enabled=True, features=["order"])
    reply = {"orders": [{"list_name": "occ",
                         "order": ["farm", "fish", "trade", "other"]}]}
    pipeline = AIPipeline(client=_client(reply))
    pipeline.run(qn, config)
    assert len(pipeline.suggestions) == 1
    assert qn.choice_lists["occ"].choice_names() == \
        ["other", "farm", "fish", "trade"]


def test_pipeline_suggestions_reset_between_runs():
    qn = _form()
    config = AIConfig(enabled=True, features=["order"])
    reply = {"orders": [{"list_name": "occ",
                         "order": ["farm", "fish", "trade", "other"]}]}
    pipeline = AIPipeline(client=_client(reply))
    pipeline.run(qn, config)
    pipeline.run(qn, AIConfig.disabled())
    assert pipeline.suggestions == []


def test_pipeline_advisory_features_fail_open():
    qn = _form()
    config = AIConfig(enabled=True,
                      features=["group", "rewrite", "order", "naming"])
    pipeline = AIPipeline(client=_failing_client("down"))
    _, notes, findings = pipeline.run(qn, config)
    assert pipeline.suggestions == []
    assert sum("Skipped" in n for n in notes) == 4
    assert findings == []                        # deterministic result stands


def test_pipeline_one_call_per_feature_per_form():
    qn = _form()
    config = AIConfig(enabled=True,
                      features=["group", "rewrite", "order", "naming"])
    client, calls = _counting_client({"sections": [], "suggestions": [],
                                      "orders": []})
    AIPipeline(client=client).run(qn, config)
    assert len(calls) == 4                       # exactly one per feature


# --- workflow end-to-end ---------------------------------------------------------------
def test_workflow_carries_suggestions_and_apply_rebuilds():
    from xlsform_studio.app.workflow import Workflow

    reply = {"orders": [{"list_name": "occ",
                         "order": ["farm", "fish", "trade", "other"]}],
             "sections": [], "suggestions": []}
    config = AIConfig(enabled=True, features=["order"])
    wf = Workflow(ai_client=_client(reply))
    result = wf.run(_form(), form_title="T", form_id="t",
                    ai_config=config, write_outputs=False)
    assert len(result.ai_suggestions) == 1
    before = result.xlsform_bytes

    wf.apply_ai_suggestions(result, result.ai_suggestions)
    assert result.ai_suggestions[0].applied
    assert result.questionnaire.choice_lists["occ"].choice_names() == \
        ["farm", "fish", "trade", "other"]
    assert result.xlsform_bytes != before        # workbook was rebuilt
    assert result.report.is_valid


def test_apply_preserves_ai_review_findings():
    from xlsform_studio.app.workflow import Workflow

    result = Workflow().run(_form(), form_title="T", form_id="t",
                            write_outputs=False)
    result.report.findings.append(
        Finding("warning", "ai_review", "Advisory note."))
    Workflow().apply_ai_suggestions(result, [])
    assert any(f.category == "ai_review" for f in result.report.findings)


# --- QA report ---------------------------------------------------------------------------
def test_qa_report_has_dedicated_ai_review_section():
    report = ValidationReport(findings=[
        Finding("warning", "structure", "A real rule warning."),
        Finding("warning", "ai_review", "An advisory AI observation.")])
    md = ReportGenerator().to_markdown(report, _form())
    assert "## AI review findings (1)" in md
    assert "Advisory only" in md
    # the AI finding is not double-counted in the rule warnings section
    warnings_section = md.split("## Warnings (1)")[1].split("##")[0]
    assert "AI observation" not in warnings_section
