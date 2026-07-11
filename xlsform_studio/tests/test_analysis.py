"""Tests for the deterministic analysis layer: consistency validator (D5),
quality scoring (D4), duration estimation (D8), choice-list normalization
(D9), the questionnaire diff engine (D3), and the AI narrative hybrid (H1)."""

from __future__ import annotations

from xlsform_studio.analysis.diff import QuestionnaireDiff
from xlsform_studio.analysis.duration import DurationEstimator
from xlsform_studio.analysis.quality_score import QualityScorer
from xlsform_studio.app.workflow import Workflow
from xlsform_studio.engine.choice_normalizer import ChoiceNormalizer
from xlsform_studio.models import (Choice, ChoiceList, FormSettings,
                                      Question, Questionnaire)
from xlsform_studio.validation.consistency_validator import (
    ConsistencyValidator)
from xlsform_studio.validation.report_generator import ReportGenerator
from xlsform_studio.validation.validator import Validator


def _base_form() -> Questionnaire:
    return Questionnaire(
        settings=FormSettings(form_title="T", form_id="t", version="1"),
        questions=[
            Question(name="resident", label="Resident?",
                     xlsform_type="select_one yes_no", list_name="yes_no"),
            Question(name="age", label="Age", xlsform_type="integer",
                     constraint=". >= 0 and . <= 120",
                     relevant="${resident}='1'"),
        ],
        choice_lists={"yes_no": ChoiceList("yes_no", [
            Choice("1", "Yes"), Choice("0", "No")])})


# --- D5: consistency validator ---------------------------------------------------
def test_circular_reference_is_error():
    qn = Questionnaire(questions=[
        Question(name="a", label="A", xlsform_type="calculate",
                 calculation="${b} + 1"),
        Question(name="b", label="B", xlsform_type="calculate",
                 calculation="${a} + 1"),
        Question(name="use", label="U", xlsform_type="note",
                 relevant="${a} > 0 and ${b} > 0")])
    findings = ConsistencyValidator().validate(qn)
    circular = [f for f in findings if "Circular" in f.message]
    assert len(circular) == 1 and circular[0].level == "error"


def test_contradictory_equalities_flagged():
    qn = _base_form()
    qn.questions[1].relevant = "${resident}='1' and ${resident}='0'"
    findings = ConsistencyValidator().validate(qn)
    assert any("can never be shown" in f.message for f in findings)


def test_contradictory_numeric_range_flagged():
    qn = _base_form()
    qn.questions[1].relevant = "${age} > 10 and ${age} < 5"
    findings = ConsistencyValidator().validate(qn)
    assert any("can never be shown" in f.message for f in findings)


def test_satisfiable_range_not_flagged():
    qn = _base_form()
    qn.questions[1].relevant = "${age} >= 5 and ${age} <= 10"
    findings = ConsistencyValidator().validate(qn)
    assert not any("can never be shown" in f.message for f in findings)


def test_or_conditions_left_alone():
    """Disjunctions are not decidable by this simple pass - never flag them."""
    qn = _base_form()
    qn.questions[1].relevant = "${resident}='1' or ${resident}='0'"
    findings = ConsistencyValidator().validate(qn)
    assert not any("can never be shown" in f.message for f in findings)


def test_forward_reference_warned():
    qn = Questionnaire(questions=[
        Question(name="early", label="E", xlsform_type="text",
                 relevant="${late}='x'"),
        Question(name="late", label="L", xlsform_type="text")])
    findings = ConsistencyValidator().validate(qn)
    assert any("only asked later" in f.message and f.level == "warning"
              for f in findings)


def test_unused_calculation_info():
    qn = Questionnaire(questions=[
        Question(name="dob", label="DOB", xlsform_type="date"),
        Question(name="age_calc", xlsform_type="calculate",
                 calculation="int((today() - ${dob}) div 365.25)")])
    findings = ConsistencyValidator().validate(qn)
    assert any("never referenced" in f.message and f.level == "info"
              for f in findings)


def test_used_calculation_not_flagged():
    qn = Questionnaire(questions=[
        Question(name="dob", label="DOB", xlsform_type="date"),
        Question(name="age_calc", xlsform_type="calculate",
                 calculation="int((today() - ${dob}) div 365.25)"),
        Question(name="preg", label="P", xlsform_type="text",
                 relevant="${age_calc} > 10")])
    findings = ConsistencyValidator().validate(qn)
    assert not any("never referenced" in f.message for f in findings)


def test_empty_group_warned():
    qn = Questionnaire(questions=[
        Question(name="g1", label="Empty", xlsform_type="begin group"),
        Question(name="", xlsform_type="end group"),
        Question(name="a", label="A", xlsform_type="text")])
    findings = ConsistencyValidator().validate(qn)
    assert any("empty" in f.message for f in findings)


def test_near_identical_lists_flagged():
    qn = Questionnaire(
        questions=[Question(name="a", xlsform_type="select_one l1"),
                   Question(name="b", xlsform_type="select_one l2")],
        choice_lists={
            "l1": ChoiceList("l1", [Choice(str(i), f"Opt {i}")
                                    for i in range(9)]),
            "l2": ChoiceList("l2", [Choice(str(i), f"Opt {i}")
                                    for i in range(1, 10)])})
    findings = ConsistencyValidator().validate(qn)
    assert any("share" in f.message for f in findings)


def test_consistency_wired_into_main_validator():
    qn = _base_form()
    qn.questions[1].relevant = "${resident}='1' and ${resident}='0'"
    report = Validator(deep=False).validate(qn)
    assert any(f.category == "consistency" for f in report.findings)


# --- D9: choice normalization -----------------------------------------------------
def test_exact_duplicate_lists_consolidated():
    qn = Questionnaire(
        questions=[
            Question(name="a", label="A", xlsform_type="select_one freq_a",
                     list_name="freq_a"),
            Question(name="b", label="B", xlsform_type="select_one freq_b",
                     list_name="freq_b")],
        choice_lists={
            "freq_a": ChoiceList("freq_a", [Choice("1", "Often"),
                                            Choice("2", "Rarely")]),
            "freq_b": ChoiceList("freq_b", [Choice("1", "Often"),
                                            Choice("2", "Rarely")])})
    notes = ChoiceNormalizer().normalize(qn)
    assert list(qn.choice_lists) == ["freq_a"]
    assert qn.questions[1].xlsform_type == "select_one freq_a"
    assert qn.questions[1].list_name == "freq_a"
    assert any("Consolidated" in n for n in notes)
    assert any("consolidated" in a for a in qn.questions[1].assumptions)


def test_different_order_not_consolidated():
    """Order matters (scales!): reordered options are NOT an exact duplicate."""
    qn = Questionnaire(
        questions=[Question(name="a", xlsform_type="select_one l1"),
                   Question(name="b", xlsform_type="select_one l2")],
        choice_lists={
            "l1": ChoiceList("l1", [Choice("1", "Yes"), Choice("0", "No")]),
            "l2": ChoiceList("l2", [Choice("0", "No"), Choice("1", "Yes")])})
    assert ChoiceNormalizer().normalize(qn) == []
    assert len(qn.choice_lists) == 2


def test_normalizer_runs_in_workflow():
    qn = Questionnaire(
        questions=[
            Question(name="a", label="A", xlsform_type="select_one la",
                     list_name="la"),
            Question(name="b", label="B", xlsform_type="select_one lb",
                     list_name="lb")],
        choice_lists={
            "la": ChoiceList("la", [Choice("1", "Often")]),
            "lb": ChoiceList("lb", [Choice("1", "Often")])})
    result = Workflow().run(qn, form_title="T", form_id="t",
                            write_outputs=False)
    kept = [k for k in result.questionnaire.choice_lists if k != "yes_no"]
    assert kept == ["la"]
    assert result.is_valid


# --- D8: duration estimator ---------------------------------------------------------
def test_duration_scales_with_form_size():
    small = DurationEstimator().estimate(_base_form())
    big = Questionnaire(questions=[
        Question(name=f"q{i}", label=f"Q{i}", xlsform_type="text")
        for i in range(60)])
    large = DurationEstimator().estimate(big)
    assert large.typical_minutes > small.typical_minutes
    assert small.low_minutes < small.typical_minutes < small.high_minutes


def test_duration_burden_bands():
    assert DurationEstimator().estimate(_base_form()).burden_risk == "low"
    heavy = Questionnaire(questions=[
        Question(name=f"q{i}", label=f"Q{i}", xlsform_type="text")
        for i in range(120)])
    assert DurationEstimator().estimate(heavy).burden_risk in ("high", "severe")


def test_duration_repeat_multiplies():
    inner = [Question(name="r", xlsform_type="begin repeat", label="HH"),
             Question(name="member_age", label="Age", xlsform_type="integer"),
             Question(name="", xlsform_type="end repeat")]
    with_repeat = DurationEstimator().estimate(Questionnaire(questions=inner))
    without = DurationEstimator().estimate(Questionnaire(
        questions=[Question(name="member_age", label="Age",
                            xlsform_type="integer")]))
    assert with_repeat.typical_minutes > without.typical_minutes * 2


def test_duration_conditional_discounted():
    always = Questionnaire(questions=[
        Question(name="a", label="A", xlsform_type="integer")])
    gated = Questionnaire(questions=[
        Question(name="a", label="A", xlsform_type="integer",
                 relevant="${x}='1'")])
    assert DurationEstimator().estimate(gated).typical_minutes < \
        DurationEstimator().estimate(always).typical_minutes


# --- D4: quality scoring ---------------------------------------------------------------
def test_quality_good_form_scores_high():
    qn = _base_form()
    report = Validator(deep=False).validate(qn)
    index = QualityScorer().score(qn, report)
    assert index.overall >= 85
    assert set(index.categories) == {
        "naming_quality", "constraint_coverage", "logic_completeness",
        "choice_consistency", "validation_readiness", "documentation",
        "reusability"}


def test_quality_penalises_missing_constraints_and_generic_names():
    qn = Questionnaire(
        settings=FormSettings(form_title="T", form_id="t", version="1"),
        questions=[Question(name=f"q{i}", label=f"Number {i}",
                            xlsform_type="integer") for i in range(5)])
    report = Validator(deep=False).validate(qn)
    index = QualityScorer().score(qn, report)
    assert index.categories["constraint_coverage"] == 0
    assert index.categories["naming_quality"] == 0
    assert any("generic" in ob for ob in index.observations)
    assert any("no validation constraint" in ob for ob in index.observations)


def test_quality_validation_errors_tank_readiness():
    qn = _base_form()
    qn.questions[1].constraint = ". >< 5"          # syntax error
    report = Validator(deep=False).validate(qn)
    index = QualityScorer().score(qn, report)
    assert index.categories["validation_readiness"] <= 60
    assert index.overall < 90


def test_quality_deterministic():
    qn = _base_form()
    report = Validator(deep=False).validate(qn)
    a = QualityScorer().score(qn, report)
    b = QualityScorer().score(qn, report)
    assert a.to_dict() == b.to_dict()


def test_workflow_always_computes_quality_and_duration():
    result = Workflow().run(_base_form(), form_title="T", form_id="t",
                            write_outputs=False)
    assert result.quality is not None and result.quality.overall > 0
    assert result.duration is not None
    assert result.duration.question_count == 2


# --- D3: diff engine ---------------------------------------------------------------------
def _v1() -> Questionnaire:
    return Questionnaire(
        settings=FormSettings(form_title="T", form_id="t", version="1"),
        questions=[
            Question(name="age", label="Age", xlsform_type="integer",
                     constraint=". >= 0 and . <= 120"),
            Question(name="sex", label="Sex", xlsform_type="select_one sexes",
                     list_name="sexes"),
            Question(name="old_q", label="Old question", xlsform_type="text")],
        choice_lists={"sexes": ChoiceList("sexes", [
            Choice("m", "Male"), Choice("f", "Female")])})


def _v2() -> Questionnaire:
    return Questionnaire(
        settings=FormSettings(form_title="T", form_id="t", version="2"),
        questions=[
            Question(name="age_years", label="Age", xlsform_type="integer",
                     constraint=". >= 0 and . <= 130"),
            Question(name="sex", label="Sex", xlsform_type="select_one sexes",
                     list_name="sexes"),
            Question(name="district", label="District", xlsform_type="text")],
        choice_lists={"sexes": ChoiceList("sexes", [
            Choice("m", "Male"), Choice("f", "Female"),
            Choice("x", "Prefer not to say")])})


def test_diff_detects_all_change_kinds():
    diff = QuestionnaireDiff.compare(_v1(), _v2())
    assert diff.renamed == [("age", "age_years")]     # same label -> rename
    assert diff.added == ["district"]
    assert diff.removed == ["old_q"]
    # the renamed question's constraint change is still reported
    assert any(c.question == "age_years" and c.field == "constraint"
              for c in diff.field_changes)
    assert diff.list_changes[0].added_options == ["x=Prefer not to say"]
    assert any(c.field == "version" for c in diff.settings_changes)


def test_diff_identical_forms_reports_no_changes():
    diff = QuestionnaireDiff.compare(_v1(), _v1())
    assert not diff.has_changes
    assert "No differences" in diff.to_markdown()


def test_diff_markdown_flags_breaking_changes():
    md = QuestionnaireDiff.compare(_v1(), _v2()).to_markdown()
    assert "Renamed variables" in md and "update analysis scripts" in md
    assert "Removed questions" in md and "longitudinal" in md


# --- H1: AI narrative + QA report sections ---------------------------------------------
def test_qa_report_includes_quality_and_duration_sections():
    qn = _base_form()
    report = Validator(deep=False).validate(qn)
    quality = QualityScorer().score(qn, report)
    duration = DurationEstimator().estimate(qn)
    md = ReportGenerator().to_markdown(report, qn, quality=quality,
                                       duration=duration)
    assert f"## Form Quality Index: {quality.overall}/100" in md
    assert "## Estimated interview duration" in md


def test_narrative_attached_by_pipeline_and_rendered():
    from xlsform_studio.ai.client import DeepSeekClient
    from xlsform_studio.ai.config import AIConfig

    client = DeepSeekClient(api_key="k")
    captured = {}

    def fake(system, user, **kw):
        captured["user"] = user
        return {"narrative": "Strong structure; low burden."}
    client.complete_json = fake

    config = AIConfig(enabled=True, features=["narrative"])
    result = Workflow(ai_client=client).run(
        _base_form(), form_title="T", form_id="t",
        ai_config=config, write_outputs=False)
    assert result.report.narrative == "Strong structure; low burden."
    # the prompt carried the audited metrics, not raw question text
    assert "quality_index" in captured["user"]
    md = ReportGenerator().to_markdown(result.report, result.questionnaire)
    assert "## Executive summary" in md
    assert "Strong structure; low burden." in md


def test_narrative_fails_open():
    from xlsform_studio.ai.client import AIError, DeepSeekClient
    from xlsform_studio.ai.config import AIConfig

    client = DeepSeekClient(api_key="k")

    def boom(*a, **kw):
        raise AIError("down")
    client.complete_json = boom

    config = AIConfig(enabled=True, features=["narrative"])
    result = Workflow(ai_client=client).run(
        _base_form(), form_title="T", form_id="t",
        ai_config=config, write_outputs=False)
    assert result.report.narrative == ""
    assert result.quality is not None          # deterministic result stands
    assert any("[AI narrative] Skipped" in n for n in result.assumptions)
