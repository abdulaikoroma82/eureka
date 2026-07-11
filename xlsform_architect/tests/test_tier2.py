"""Tests for Tier-2 roadmap items: domain rule packs (D7), missing-question
detection (A4), and the objective-coverage matrix (A5/H2)."""

from __future__ import annotations

import pytest

from xlsform_architect.ai.client import AIError, DeepSeekClient
from xlsform_architect.ai.completeness import AICompletenessReviewer
from xlsform_architect.ai.config import AIConfig
from xlsform_architect.ai.coverage import AICoverageReviewer
from xlsform_architect.ai.pipeline import AIPipeline
from xlsform_architect.app.workflow import Workflow
from xlsform_architect.engine.knowledge_base import KnowledgeBase
from xlsform_architect.models import (FormSettings, Question, Questionnaire)


def _client(reply: dict) -> DeepSeekClient:
    client = DeepSeekClient(api_key="test-key")
    client.complete_json = lambda *a, **kw: reply  # type: ignore[method-assign]
    return client


def _failing_client() -> DeepSeekClient:
    client = DeepSeekClient(api_key="test-key")

    def boom(*a, **kw):
        raise AIError("down")
    client.complete_json = boom  # type: ignore[method-assign]
    return client


def _anthro_form() -> Questionnaire:
    return Questionnaire(
        settings=FormSettings(form_title="Nutrition Survey", form_id="nut"),
        questions=[
            Question(name="child_weight", raw_label="Child weight (kg)",
                     label="Child weight (kg)"),
            Question(name="child_muac", raw_label="Child MUAC",
                     label="Child MUAC"),
        ])


# --- D7: domain rule packs ---------------------------------------------------------
def test_available_packs_lists_all_five():
    packs = KnowledgeBase.available_packs()
    for expected in ("nutrition", "health", "agriculture", "education",
                     "humanitarian"):
        assert expected in packs


def test_unknown_pack_raises_with_available_names():
    with pytest.raises(FileNotFoundError, match="nutrition"):
        KnowledgeBase.load(packs=["fisheries"])


def test_no_packs_is_identical_to_neutral_rules():
    assert KnowledgeBase.load().xlsform_rules == \
        KnowledgeBase.load(packs=[]).xlsform_rules


def test_nutrition_pack_constrains_muac_end_to_end():
    """Acceptance criterion: the pack bounds a MUAC question the neutral
    rules leave open."""
    neutral = Workflow().run(_anthro_form(), form_title="N", form_id="n",
                             write_outputs=False)
    muac_neutral = next(q for q in neutral.questionnaire.questions
                        if "muac" in q.name)
    assert muac_neutral.constraint == ""       # neutral rules: no bound

    kb = KnowledgeBase.load(packs=["nutrition"])
    packed = Workflow(knowledge=kb).run(_anthro_form(), form_title="N",
                                        form_id="n", write_outputs=False)
    muac = next(q for q in packed.questionnaire.questions
                if "muac" in q.name)
    assert muac.xlsform_type == "decimal"      # pack keyword classified it
    assert muac.constraint == ". >= 60 and . <= 400"
    weight = next(q for q in packed.questionnaire.questions
                  if "weight" in q.name)
    assert weight.constraint == ". >= 0.5 and . <= 300"
    assert packed.is_valid


def test_pack_specific_rule_wins_over_generic_pack_rule():
    """'muac (cm)' must hit the cm template, not the generic mm one."""
    kb = KnowledgeBase.load(packs=["nutrition"])
    qn = Questionnaire(questions=[
        Question(name="m", raw_label="Child MUAC (cm)",
                 label="Child MUAC (cm)")])
    result = Workflow(knowledge=kb).run(qn, form_title="N", form_id="n",
                                        write_outputs=False)
    assert result.questionnaire.questions[0].constraint == \
        ". >= 6 and . <= 40"


def test_packs_stack():
    kb = KnowledgeBase.load(packs=["nutrition", "health"])
    assert kb.packs == ["nutrition", "health"]
    qn = Questionnaire(questions=[
        Question(name="t", raw_label="Body temperature",
                 label="Body temperature"),
        Question(name="m", raw_label="MUAC", label="MUAC")])
    result = Workflow(knowledge=kb).run(qn, form_title="N", form_id="n",
                                        write_outputs=False)
    constraints = {q.constraint for q in result.questionnaire.questions}
    assert ". >= 30 and . <= 45" in constraints     # health pack fired
    assert ". >= 60 and . <= 400" in constraints    # nutrition pack fired


def test_neutral_age_rule_still_applies_with_pack():
    """Packs extend the neutral rules; they don't replace them."""
    kb = KnowledgeBase.load(packs=["nutrition"])
    qn = Questionnaire(questions=[
        Question(name="a", raw_label="Respondent age",
                 label="Respondent age")])
    result = Workflow(knowledge=kb).run(qn, form_title="N", form_id="n",
                                        write_outputs=False)
    assert result.questionnaire.questions[0].constraint == \
        ". >= 0 and . <= 120"


# --- A4: missing question detection ---------------------------------------------------
def test_completeness_flags_missing_items_advisory_only():
    qn = _anthro_form()
    reply = {"missing": [{"item": "Child height/length (cm)",
                          "reason": "weight-for-height cannot be computed "
                                    "without it"}]}
    findings = AICompletenessReviewer(_client(reply)).review(
        qn, survey_context="SMART nutrition survey")
    assert len(findings) == 1
    f = findings[0]
    assert f.level == "warning" and f.category == "ai_review"
    assert "Potentially missing: Child height/length (cm)" in f.message
    assert "never adds questions" in f.message
    # the form itself is untouched - no question was added
    assert len(qn.questions) == 2


def test_completeness_empty_and_failure_paths():
    qn = _anthro_form()
    assert AICompletenessReviewer(_client({"missing": []})).review(qn) == []
    findings = AICompletenessReviewer(_failing_client()).review(qn)
    assert len(findings) == 1 and findings[0].level == "info"


# --- A5/H2: objective coverage ----------------------------------------------------------
def _coverage_reply():
    return {"coverage": [
        {"objective": "Estimate acute malnutrition",
         "questions": ["child_weight", "child_muac"], "rating": "partial",
         "gap": "no height/length for weight-for-height"},
        {"objective": "Measure water access",
         "questions": [], "rating": "none", "gap": ""},
    ]}


def test_coverage_matrix_built_and_gaps_flagged():
    matrix, notes, findings = AICoverageReviewer(_client(_coverage_reply())).review(
        _anthro_form(),
        "Estimate acute malnutrition\nMeasure water access")
    assert "# Objective Coverage Matrix" in matrix
    assert "`child_weight`, `child_muac`" in matrix
    assert "❌ none" in matrix
    # both non-full objectives produce advisory findings
    assert len(findings) == 2
    assert all(f.category == "ai_review" and f.level == "warning"
              for f in findings)


def test_coverage_discards_nonexistent_question_references():
    reply = {"coverage": [{"objective": "Estimate acute malnutrition",
                           "questions": ["ghost_question"],
                           "rating": "full", "gap": ""}]}
    matrix, notes, findings = AICoverageReviewer(_client(reply)).review(
        _anthro_form(), "Estimate acute malnutrition")
    assert any("ghost_question" in n and "Discarded" in n for n in notes)
    # rating degraded to none because no VALID question supports it
    assert "❌ none" in matrix
    assert len(findings) == 1


def test_coverage_skipped_without_objectives():
    matrix, notes, findings = AICoverageReviewer(
        _client(_coverage_reply())).review(_anthro_form(), "")
    assert matrix == "" and notes == [] and findings == []


def test_coverage_end_to_end_writes_artifact(tmp_path):
    config = AIConfig(enabled=True, features=["coverage"],
                      objectives="Estimate acute malnutrition\n"
                                 "Measure water access")
    result = Workflow(ai_client=_client(_coverage_reply())).run(
        _anthro_form(), form_title="N", form_id="n",
        ai_config=config, output_dir=tmp_path, write_outputs=True)
    assert result.coverage_matrix
    path = result.outputs.get("coverage_matrix")
    assert path is not None and path.exists()
    assert "Objective Coverage Matrix" in path.read_text(encoding="utf-8")


def test_pipeline_coverage_matrix_resets_between_runs():
    pipeline = AIPipeline(client=_client(_coverage_reply()))
    config = AIConfig(enabled=True, features=["coverage"],
                      objectives="Estimate acute malnutrition")
    pipeline.run(_anthro_form(), config)
    assert pipeline.coverage_matrix
    pipeline.run(_anthro_form(), AIConfig.disabled())
    assert pipeline.coverage_matrix == ""
