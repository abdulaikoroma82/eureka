"""Tests for domain-pack bound backfill in the AI-first workflow.

The AI author never reads the domain packs; :class:`PackBackfill` fills the
bounds it left blank. These tests drive the real AI-first workflow with a
canned client (no network) and check the pack bound lands only where the AI
wrote none, is logged, and that runs without packs are untouched."""

from __future__ import annotations

from xlsform_studio.app.workflow import Workflow
from xlsform_studio.engine.knowledge_base import KnowledgeBase
from xlsform_studio.engine.pack_backfill import PackBackfill
from xlsform_studio.models import Question, Questionnaire

PZQ = ". >= 0 and . <= 5 and (. * 2) mod 1 = 0"


class FakeClient:
    """Canned DeepSeek client returning a fixed authoring payload."""

    available = True

    def __init__(self, payload: dict):
        self._payload = payload

    def complete_json(self, system_prompt, user_prompt, max_tokens=4000,
                      temperature=0.0):
        return self._payload


SURVEY = [
    {"question": "How many praziquantel tablets did you swallow?"},
    {"question": "MUAC (mm)"},
    {"question": "Number of ivermectin tablets given"},
    {"question": "Reason for not taking praziquantel"},
    {"question": "Village name"},
]


def _payload(ivermectin_constraint: str = ". >= 0 and . <= 10"):
    """AI rows: PZQ and MUAC unbounded, ivermectin with the AI's own
    (looser) bound, a free-text reason, and an unrelated text item."""
    return {"questions": [
        {"index": 0, "type": "decimal", "name": "pzq_tablets",
         "label": "Praziquantel tablets swallowed", "confidence": "high"},
        {"index": 1, "type": "integer", "name": "muac",
         "label": "MUAC (mm)", "confidence": "high"},
        {"index": 2, "type": "integer", "name": "ivm_tablets",
         "label": "Ivermectin tablets given",
         "constraint": ivermectin_constraint,
         "constraint_message": "AI message", "confidence": "high"},
        {"index": 3, "type": "text", "name": "pzq_reason",
         "label": "Reason for not taking praziquantel", "confidence": "high"},
        {"index": 4, "type": "text", "name": "village",
         "label": "Village name", "confidence": "high"},
    ], "choices": {}}


def _run(packs, payload=None):
    kb = KnowledgeBase.load(packs=list(packs))
    wf = Workflow(knowledge=kb, ai_client=FakeClient(payload or _payload()))
    result = wf.run_from_dict({"settings": {"form_title": "MDA"},
                               "survey": SURVEY},
                              authoring="ai", write_outputs=False)
    return result, {q.name: q for q in result.questionnaire.questions}


def test_backfill_fills_unbounded_ai_question_from_pack():
    result, qs = _run(["ntd"])
    assert qs["pzq_tablets"].constraint == PZQ
    assert "Praziquantel" in qs["pzq_tablets"].constraint_message
    assert result.is_valid


def test_backfill_fills_from_every_loaded_pack():
    _, qs = _run(["nutrition", "ntd"])
    assert qs["pzq_tablets"].constraint == PZQ                  # ntd
    assert qs["muac"].constraint == ". >= 60 and . <= 400"       # nutrition


def test_backfill_keeps_ai_constraint_even_if_looser_than_pack():
    _, qs = _run(["ntd"])
    ivm = qs["ivm_tablets"]
    assert ivm.constraint == ". >= 0 and . <= 10"   # AI's, not the pack's 0-4
    assert ivm.constraint_message == "AI message"


def test_backfill_ignores_text_and_unmatched_questions():
    _, qs = _run(["ntd"])
    assert qs["pzq_reason"].constraint == ""        # text: never bounded
    assert qs["village"].constraint == ""
    assert qs["muac"].constraint == ""              # nutrition not loaded


def test_backfill_ignores_type_outside_template_applies_to():
    """The Kato-Katz per-slide rule applies to integers only."""
    qn = Questionnaire(questions=[Question(
        name="slide", raw_label="Eggs per slide", xlsform_type="decimal")])
    assert PackBackfill(KnowledgeBase.load(packs=["ntd"])).apply(qn) == []
    assert qn.questions[0].constraint == ""


def test_backfill_no_pack_run_is_unchanged():
    """No packs: nothing filled - not even from the neutral rules (the
    neutral 'number of' rule would otherwise add '. >= 0')."""
    result, qs = _run([])
    assert all(not q.constraint for n, q in qs.items() if n != "ivm_tablets")
    assert not any("[Domain pack]" in n for n in result.assumptions)
    assert PackBackfill(KnowledgeBase.load()).apply(result.questionnaire) == []


def test_backfill_is_logged_as_decision_and_note():
    result, qs = _run(["ntd"])
    decision = next(d for d in qs["pzq_tablets"].decisions
                    if d.field_name == "constraint")
    assert decision.value == PZQ
    assert "'ntd' domain pack" in decision.reason
    assert any("'ntd' domain pack" in a
               for a in qs["pzq_tablets"].assumptions)
    notes = [n for n in result.assumptions if n.startswith("[Domain pack]")]
    assert notes == ["[Domain pack] Applied 1 pack bound(s) the AI left "
                     "unbounded: pzq_tablets (ntd)."]


def test_backfill_later_pack_matches_first():
    """Pack order mirrors the merged rules: the last-loaded pack wins."""
    kb = KnowledgeBase.load(packs=["nutrition", "ntd"])
    assert kb.pack_constraints[0][0] == "ntd"
    assert [t for _, t in kb.pack_constraints] == \
        kb.constraint_templates()[:len(kb.pack_constraints)]
