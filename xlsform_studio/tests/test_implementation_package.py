"""Tests for Tier-1 roadmap items: deployment readiness validation (D10),
the survey implementation package (D6), and enumerator instruction
suggestions (A9)."""

from __future__ import annotations

from xlsform_studio.ai.client import DeepSeekClient
from xlsform_studio.ai.config import AIConfig
from xlsform_studio.ai.enumerator_notes import AIEnumeratorNoteSuggester
from xlsform_studio.ai.suggestions import AISuggestion, apply_suggestions
from xlsform_studio.analysis.duration import DurationEstimator
from xlsform_studio.app.artifacts import ArtifactBuilder
from xlsform_studio.app.workflow import Workflow
from xlsform_studio.models import (Choice, ChoiceList, FormSettings,
                                      Question, Questionnaire)
from xlsform_studio.validation.readiness_validator import (
    ReadinessValidator)
from xlsform_studio.validation.validator import Validator


def _client(reply: dict) -> DeepSeekClient:
    client = DeepSeekClient(api_key="test-key")
    client.complete_json = lambda *a, **kw: reply  # type: ignore[method-assign]
    return client


def _form() -> Questionnaire:
    return Questionnaire(
        settings=FormSettings(form_title="T", form_id="t", version="1"),
        questions=[
            Question(name="water_sources", label="Water sources used?",
                     xlsform_type="select_multiple ws", list_name="ws",
                     section="WASH"),
            Question(name="age", label="Respondent age",
                     xlsform_type="integer", section="WASH",
                     constraint=". >= 0 and . <= 120",
                     constraint_message="Age must be 0-120.",
                     relevant="${water_sources}!=''"),
            Question(name="water_sources_other", label="Please specify other",
                     xlsform_type="text", section="WASH",
                     relevant="selected(${water_sources}, 'other')"),
        ],
        choice_lists={"ws": ChoiceList("ws", [
            Choice("piped", "Piped water"), Choice("well", "Well"),
            Choice("other", "Other")])})


# --- D10: readiness validator ---------------------------------------------------
def test_incomplete_translation_flagged_with_specifics():
    qn = _form()
    qn.questions[0].extra["label::French (fr)"] = "Sources d'eau ?"
    findings = ReadinessValidator().validate(qn)
    hits = [f for f in findings if "label::French (fr)" in f.message]
    assert len(hits) == 1 and hits[0].level == "warning"
    # untranslated question AND untranslated choices are itemised
    assert "question 'age'" in hits[0].message
    assert "choice 'piped'" in hits[0].message


def test_complete_translation_not_flagged():
    qn = _form()
    qn.settings.default_language = "English (en)"
    for q in qn.questions:
        q.extra["label::French (fr)"] = "fr"
    for c in qn.choice_lists["ws"].choices:
        c.extra["label::French (fr)"] = "fr"
    findings = ReadinessValidator().validate(qn)
    assert not any("incomplete" in f.message for f in findings)


def test_missing_default_language_flagged_only_with_translations():
    qn = _form()
    assert not any("default_language" in f.message
                  for f in ReadinessValidator().validate(qn))
    qn.questions[0].extra["label::French (fr)"] = "fr"
    assert any("default_language" in f.message
              for f in ReadinessValidator().validate(qn))


def test_media_manifest_and_empty_media():
    qn = _form()
    qn.questions[0].extra["media::image"] = "well_types.png"
    qn.questions[1].extra["media::audio"] = "   "
    findings = ReadinessValidator().validate(qn)
    assert any("well_types.png" in f.message and f.level == "info"
              for f in findings)
    assert any("empty media::audio" in f.message and f.level == "warning"
              for f in findings)


def test_long_list_without_search_appearance_flagged():
    qn = Questionnaire(questions=[
        Question(name="district", label="District",
                 xlsform_type="select_one d", list_name="d")],
        choice_lists={"d": ChoiceList("d", [
            Choice(str(i), f"District {i}") for i in range(60)])})
    findings = ReadinessValidator().validate(qn)
    assert any("60 options" in f.message for f in findings)
    qn.questions[0].appearance = "autocomplete"
    findings = ReadinessValidator().validate(qn)
    assert not any("60 options" in f.message for f in findings)


def test_readiness_wired_into_main_validator():
    qn = _form()
    qn.questions[0].extra["label::French (fr)"] = "fr"
    report = Validator(deep=False).validate(qn)
    assert any(f.category == "readiness" for f in report.findings)
    assert report.is_valid          # readiness findings never block


# --- D6: implementation package ----------------------------------------------------
def test_enumerator_guide_content():
    qn = _form()
    qn.questions[1].hint = "Estimate if unknown."
    duration = DurationEstimator().estimate(qn)
    md = ArtifactBuilder().enumerator_guide_markdown(qn, duration=duration)
    assert "# Enumerator Reference Guide" in md
    assert "## WASH" in md
    assert "**1. Water sources used?**" in md
    assert "Select ALL options that apply." in md
    assert "Piped water; Well; Other" in md
    assert "Ask only when:" in md               # skip rule, prettified
    assert "*Valid answers:* Age must be 0-120." in md
    assert "*Note:* Estimate if unknown." in md


def test_variable_specification_includes_assumptions():
    qn = _form()
    qn.questions[1].add_assumption("Classified as integer from 'age'.")
    df = ArtifactBuilder().variable_specification_frame(qn)
    row = df[df["variable"] == "age"].iloc[0]
    assert "Classified as integer" in row["assumptions"]
    assert "constraint" in df.columns


def test_collection_plan_content():
    qn = _form()
    qn.questions[0].extra["media::image"] = "well_types.png"
    qn.questions[0].xlsform_type = "select_multiple ws"
    qn.questions.append(Question(name="loc", label="Location",
                                 xlsform_type="geopoint", section="WASH"))
    duration = DurationEstimator().estimate(qn)
    md = ArtifactBuilder().collection_plan_markdown(qn, duration=duration)
    assert "# Data Collection Plan" in md
    assert "interviews per enumerator" in md
    assert "GPS enabled" in md
    assert "well_types.png" in md
    assert "Sampling design" in md              # manual-completion checklist


def test_workflow_writes_implementation_package(tmp_path):
    result = Workflow().run(_form(), form_title="T", form_id="t",
                            output_dir=tmp_path, write_outputs=True)
    for key in ("enumerator_guide", "variable_specification",
                "collection_plan"):
        assert key in result.outputs and result.outputs[key].exists()


# --- A9: enumerator instruction suggestions ------------------------------------------
def test_enumerator_notes_suggested_for_hintless_questions_only():
    qn = _form()
    qn.questions[1].hint = "Author hint."       # must not be offered
    captured = {}
    client = DeepSeekClient(api_key="k")

    def fake(system, user, **kw):
        captured["user"] = user
        return {"suggestions": [{"question_name": "water_sources",
                                 "hint": "Probe for all sources; do not read the list aloud.",
                                 "reason": "multi-select needs probing"}]}
    client.complete_json = fake

    notes, suggestions = AIEnumeratorNoteSuggester(client).suggest(qn)
    assert "age" not in captured["user"]        # hinted question not offered
    assert len(suggestions) == 1
    assert suggestions[0].kind == "hint"
    assert qn.questions[0].hint == ""           # advisory: nothing applied


def test_enumerator_note_rejected_for_hinted_question():
    qn = _form()
    reply = {"suggestions": [{"question_name": "age", "hint": "x"}]}
    qn.questions[1].hint = "Author hint."
    notes, suggestions = AIEnumeratorNoteSuggester(_client(reply)).suggest(qn)
    assert suggestions == []
    assert any("stays authoritative" in n for n in notes)


def test_enumerator_note_rejected_when_too_long():
    qn = _form()
    reply = {"suggestions": [{"question_name": "water_sources",
                              "hint": "x" * 300}]}
    notes, suggestions = AIEnumeratorNoteSuggester(_client(reply)).suggest(qn)
    assert suggestions == []
    assert any("too long" in n for n in notes)


def test_hint_apply_and_author_hint_wins_at_apply_time():
    qn = _form()
    sug = AISuggestion(kind="hint", target="water_sources",
                       original="(no hint)", suggested="Probe fully.",
                       payload={"hint": "Probe fully."})
    apply_suggestions(qn, [sug])
    assert qn.questions[0].hint == "Probe fully."
    assert any("enumerator instruction accepted" in a
              for a in qn.questions[0].assumptions)

    # stale acceptance: an author hint appeared since the suggestion
    qn2 = _form()
    qn2.questions[0].hint = "Author wrote this meanwhile."
    sug2 = AISuggestion(kind="hint", target="water_sources",
                        original="(no hint)", suggested="AI text",
                        payload={"hint": "AI text"})
    notes = apply_suggestions(qn2, [sug2])
    assert qn2.questions[0].hint == "Author wrote this meanwhile."
    assert not sug2.applied
    assert any("author-written hint" in n for n in notes)


def test_instructions_feature_wired_into_pipeline():
    from xlsform_studio.ai.pipeline import AIPipeline

    qn = _form()
    config = AIConfig(enabled=True, features=["instructions"])
    reply = {"suggestions": [{"question_name": "water_sources",
                              "hint": "Probe for all sources."}]}
    pipeline = AIPipeline(client=_client(reply))
    pipeline.run(qn, config)
    assert len(pipeline.suggestions) == 1
    assert pipeline.suggestions[0].kind == "hint"


