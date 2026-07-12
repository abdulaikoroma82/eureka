"""Tests for the AI document co-writer and its deterministic slotting.

The supporting documents are authored deterministically; the "documents"
feature lets the model co-write only their framing prose, which the builders
slot into labelled positions. These tests use a fake DeepSeek client so no
network call or API key is needed, and assert both that the prose lands and
that every document is unchanged when the feature is off (offline-first).
"""

from __future__ import annotations

from xlsform_studio.ai.client import AIError
from xlsform_studio.ai.config import AIConfig
from xlsform_studio.ai.document_writer import AIDocumentWriter
from xlsform_studio.app.artifacts import ArtifactBuilder
from xlsform_studio.app.verification_checklist import VerificationChecklistBuilder
from xlsform_studio.app.workflow import Workflow
from xlsform_studio.models import Question, Questionnaire


_PROSE_PAYLOAD = {
    "enumerator_intro": "Use this guide in the field; the device enforces "
                        "skip rules for you.",
    "collection_plan_overview": "This instrument captures household water "
                                "access across two short sections.",
    "logic_overview": "A few questions appear only when earlier answers "
                      "warrant them, and numeric answers are range-checked.",
    "instrument_intro": "A paper copy of the digital questionnaire.",
    "assumptions_intro": "Review the automatic decisions below before you "
                         "deploy, starting with the critical tier.",
}


class FakeClient:
    """Canned client that returns a fixed payload for any prompt."""

    available = True

    def __init__(self, payload):
        self._payload = payload

    def complete_json(self, system_prompt, user_prompt, max_tokens=4000,
                      temperature=0.0):
        return self._payload


class RoutingClient:
    """Routes by system prompt so one client can serve both the form author
    and the document co-writer within a single workflow run."""

    available = True

    def __init__(self, form_payload, prose_payload):
        self._form = form_payload
        self._prose = prose_payload

    def complete_json(self, system_prompt, user_prompt, max_tokens=4000,
                      temperature=0.0):
        if "documentation editor" in system_prompt:
            return self._prose
        return self._form


def _qn():
    return Questionnaire(questions=[
        Question(name="age", label="Age", xlsform_type="integer",
                 constraint=". >= 0", section="Household"),
        Question(name="adult", label="Adult?", xlsform_type="text",
                 relevant="${age} >= 18", section="Household")])


# --- AIDocumentWriter --------------------------------------------------------
def test_writer_returns_all_blocks_and_a_note():
    prose, notes = AIDocumentWriter(FakeClient(_PROSE_PAYLOAD)).write(_qn())
    assert prose.any
    assert prose.enumerator_intro.startswith("Use this guide")
    assert prose.logic_overview
    assert any("Co-wrote" in n for n in notes)


def test_writer_no_client_is_silent_noop():
    prose, notes = AIDocumentWriter(client=None).write(_qn())
    assert not prose.any
    assert notes == []


def test_writer_fails_open_on_ai_error():
    class Boom:
        available = True

        def complete_json(self, *a, **k):
            raise AIError("boom")

    prose, notes = AIDocumentWriter(Boom()).write(_qn())
    assert not prose.any
    assert any("Skipped" in n for n in notes)


def test_writer_sanitises_and_caps_prose():
    huge = {"logic_overview": "x " * 2000}
    prose, _ = AIDocumentWriter(FakeClient(huge)).write(_qn())
    assert len(prose.logic_overview) <= 1200
    # collapsed whitespace, no runaway
    assert "  " not in prose.logic_overview


# --- deterministic slotting --------------------------------------------------
def test_enumerator_guide_slots_intro_labelled():
    md = ArtifactBuilder().enumerator_guide_markdown(
        _qn(), intro="Field orientation here.")
    assert "**AI-written.**" in md
    assert "Field orientation here." in md


def test_logic_map_slots_overview_labelled():
    md = ArtifactBuilder().logic_map_markdown(_qn(), overview="How logic works.")
    assert "**AI-written.**" in md
    assert "How logic works." in md
    # the authoritative table is still present
    assert "Shown when" in md


def test_collection_plan_slots_overview_labelled():
    md = ArtifactBuilder().collection_plan_markdown(
        _qn(), overview="What this collects.")
    assert "**AI-written.**" in md
    assert "What this collects." in md
    assert "## Instrument overview" in md


def test_checklist_slots_intro_labelled():
    md = VerificationChecklistBuilder().build_markdown(
        _qn(), ["[age] Default 'integer' constraint applied."],
        intro="Verify these first.")
    assert "**AI-written.**" in md
    assert "Verify these first." in md
    assert "Critical" in md  # deterministic tiers intact


def test_documents_unchanged_without_prose():
    """Offline invariant: empty prose leaves every document byte-for-byte
    what it was before the feature existed."""
    b = ArtifactBuilder()
    qn = _qn()
    assert "AI-written" not in b.enumerator_guide_markdown(qn)
    assert "AI-written" not in b.logic_map_markdown(qn)
    assert "AI-written" not in b.collection_plan_markdown(qn)
    assert "AI-written" not in VerificationChecklistBuilder().build_markdown(
        qn, ["[age] note"])


# --- pipeline gating ---------------------------------------------------------
def test_pipeline_write_documents_gated_off_by_default():
    from xlsform_studio.ai.pipeline import AIPipeline
    prose, notes = AIPipeline(FakeClient(_PROSE_PAYLOAD)).write_documents(
        _qn(), None, None, None, AIConfig.disabled())
    assert not prose.any
    assert notes == []


# --- workflow integration ----------------------------------------------------
def _form_payload():
    return {"questions": [
        {"index": 0, "type": "integer", "name": "age", "label": "Age",
         "constraint": ". >= 0", "confidence": "high"},
        {"index": 1, "type": "text", "name": "adult", "label": "Adult?",
         "relevant": "${age} >= 18", "confidence": "high"}],
        "choices": {}}


def test_workflow_cowrites_documents_end_to_end(tmp_path):
    client = RoutingClient(_form_payload(), _PROSE_PAYLOAD)
    cfg = AIConfig(enabled=True, features=["documents"])
    result = Workflow(ai_client=client).run_from_dict(
        {"settings": {"form_title": "Water", "form_id": "water"},
         "survey": [{"question": "Age"}, {"question": "Adult?"}]},
        authoring="ai", ai_config=cfg, ai_client=client,
        output_dir=tmp_path, write_outputs=True)

    assert result.document_prose.any
    guide = (result.outputs["enumerator_guide"]).read_text(encoding="utf-8")
    assert "**AI-written.**" in guide
    plan = (result.outputs["collection_plan"]).read_text(encoding="utf-8")
    assert "This instrument captures" in plan
