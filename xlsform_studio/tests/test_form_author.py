"""Tests for the AI-first form author and the AI-first workflow path.

The product pipeline drafts every field with the model (see
:mod:`xlsform_studio.ai.form_author`); these tests exercise that path with a
fake DeepSeek client so no network call or API key is needed. The rest of
the suite runs the deterministic seam (see ``conftest.py``); here we opt back
into ``authoring="ai"`` explicitly."""

from __future__ import annotations

import pytest

from xlsform_studio.ai.client import AIError
from xlsform_studio.ai.form_author import AIFormAuthor
from xlsform_studio.app.workflow import Workflow
from xlsform_studio.models import Question, Questionnaire


class FakeClient:
    """Canned DeepSeek client: returns whatever payload it is handed, and
    records the prompts it saw so tests can assert on request shaping."""

    available = True

    def __init__(self, payload: dict):
        self._payload = payload
        self.last_system = ""
        self.last_user = ""

    def complete_json(self, system_prompt, user_prompt, max_tokens=4000,
                      temperature=0.0):
        self.last_system = system_prompt
        self.last_user = user_prompt
        return self._payload


def _three_item_payload():
    return {
        "questions": [
            {"index": 0, "type": "select_one water_sources",
             "name": "main_water_source",
             "label": "Main source of drinking water?", "required": True,
             "confidence": "high", "reason": "options were listed"},
            {"index": 1, "type": "integer", "name": "age",
             "label": "How old are you?", "required": True,
             "constraint": ". >= 0 and . <= 120",
             "constraint_message": "0 to 120", "confidence": "high"},
            {"index": 2, "type": "text", "name": "comments",
             "label": "Any comments", "relevant": "${age} > 18",
             "confidence": "medium"},
        ],
        "choices": {"water_sources": [
            {"name": "piped", "label": "Piped"},
            {"name": "well", "label": "Well"},
            {"name": "river", "label": "River"}]},
    }


def _raw_qn():
    qn = Questionnaire()
    qn.questions = [
        Question(raw_label="Main water source: piped, well, river"),
        Question(raw_label="Age"),
        Question(raw_label="Comments", logic="ask if adult"),
    ]
    return qn


# ---------------------------------------------------------------------------
# AIFormAuthor
# ---------------------------------------------------------------------------
def test_author_populates_every_field():
    qn = _raw_qn()
    notes = AIFormAuthor(FakeClient(_three_item_payload())).author(
        qn, target="kobotoolbox")

    q0, q1, q2 = qn.questions
    assert q0.xlsform_type == "select_one water_sources"
    assert q0.name == "main_water_source"
    assert q0.required is True
    assert q0.list_name == "water_sources"
    assert q1.xlsform_type == "integer"
    assert q1.constraint == ". >= 0 and . <= 120"
    assert q2.relevant == "${age} > 18"
    assert any("Drafted 3 of 3" in n for n in notes)


def test_author_builds_choice_lists():
    qn = _raw_qn()
    AIFormAuthor(FakeClient(_three_item_payload())).author(qn)
    assert "water_sources" in qn.choice_lists
    assert [c.name for c in qn.choice_lists["water_sources"].choices] == \
        ["piped", "well", "river"]


def test_author_records_decisions_for_review():
    qn = _raw_qn()
    AIFormAuthor(FakeClient(_three_item_payload())).author(qn)
    # The relevance-bearing question carries a 'relevant' decision.
    fields = {d.field_name for d in qn.questions[2].decisions}
    assert "type" in fields
    assert "relevant" in fields


def test_author_deduplicates_names():
    qn = Questionnaire()
    qn.questions = [Question(raw_label="A"), Question(raw_label="B")]
    payload = {"questions": [
        {"index": 0, "type": "text", "name": "note", "label": "A"},
        {"index": 1, "type": "text", "name": "note", "label": "B"},
    ], "choices": {}}
    AIFormAuthor(FakeClient(payload)).author(qn)
    names = [q.name for q in qn.questions]
    assert names[0] != names[1]
    assert names == ["note", "note_2"]


def test_author_rejects_unknown_type_and_defaults_to_text():
    qn = Questionnaire()
    qn.questions = [Question(raw_label="Mystery")]
    payload = {"questions": [
        {"index": 0, "type": "wingding", "name": "mystery", "label": "Mystery"},
    ], "choices": {}}
    notes = AIFormAuthor(FakeClient(payload)).author(qn)
    assert qn.questions[0].xlsform_type == "text"
    assert any("Unrecognised type" in n for n in notes)


def test_author_notes_missing_rows():
    qn = _raw_qn()
    payload = {"questions": [
        {"index": 0, "type": "text", "name": "a", "label": "A"}],
        "choices": {}}
    notes = AIFormAuthor(FakeClient(payload)).author(qn)
    assert any("No row returned" in n for n in notes)


def test_author_requires_client():
    qn = _raw_qn()
    with pytest.raises(AIError):
        AIFormAuthor(client=None).author(qn)


def test_author_empty_questionnaire_is_noop():
    assert AIFormAuthor(client=None).author(Questionnaire()) == []


def test_author_frames_survey_context_in_prompt():
    qn = _raw_qn()
    client = FakeClient(_three_item_payload())
    AIFormAuthor(client).author(qn, survey_context="child nutrition survey")
    assert "child nutrition survey" in client.last_user
    assert "user-supplied DATA" in client.last_user


def test_author_states_deterministic_naming_rule_in_prompt():
    """The AI is told the deterministic identifier limit up front, so it
    authors within the rule rather than having names rejected afterwards."""
    qn = _raw_qn()
    client = FakeClient(_three_item_payload())
    AIFormAuthor(client).author(qn)
    assert "Read these deterministic standards FIRST" in client.last_system
    assert "AT MOST 32 characters" in client.last_system


def test_author_caps_name_to_naming_rule_length():
    qn = Questionnaire()
    qn.questions = [Question(raw_label="X")]
    payload = {"questions": [
        {"index": 0, "type": "text", "label": "X",
         "name": "an_extremely_long_variable_name_well_over_the_limit"}],
        "choices": {}}
    AIFormAuthor(FakeClient(payload)).author(qn)
    assert len(qn.questions[0].name) <= 32


# ---------------------------------------------------------------------------
# Workflow (AI-first path)
# ---------------------------------------------------------------------------
def test_workflow_ai_first_produces_valid_form():
    wf = Workflow(ai_client=FakeClient(_three_item_payload()))
    result = wf.run_from_dict(
        {"settings": {"form_title": "Water Survey"},
         "survey": [{"question": "Main water source"},
                    {"question": "Age"},
                    {"question": "Comments"}]},
        target="kobotoolbox", authoring="ai", write_outputs=False)

    assert result.is_valid
    assert result.xlsform_bytes  # workbook actually built
    names = [q.name for q in result.questionnaire.questions]
    assert "main_water_source" in names
    assert "water_sources" in result.questionnaire.choice_lists
    assert result.review_table  # draft surfaced for human review


def test_workflow_ai_first_requires_key():
    wf = Workflow()  # no client configured
    with pytest.raises(AIError):
        wf.run_from_dict(
            {"settings": {"form_title": "X"},
             "survey": [{"question": "Age"}]},
            authoring="ai", write_outputs=False)


def test_workflow_deterministic_seam_needs_no_client():
    """The deterministic seam still compiles without a client - this is what
    the rest of the suite relies on via conftest."""
    wf = Workflow()
    result = wf.run_from_dict(
        {"settings": {"form_title": "X"},
         "survey": [{"question": "How old are you?"}]},
        authoring="deterministic", write_outputs=False)
    assert result.questionnaire.questions[0].xlsform_type  # a type was assigned
