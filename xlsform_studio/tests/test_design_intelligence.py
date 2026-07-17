"""Tests for the Survey Design Score - the deterministic methodological
scorer (analysis/design_intelligence.py).

Each dimension is exercised with a form that should trip it and one that
shouldn't, plus the honesty behaviours (objective coverage marked "not
assessed" without objectives) and the workflow integration (the score is
always computed and a survey_design_report.md is written).
"""

from __future__ import annotations

from xlsform_studio.analysis.design_intelligence import (DesignIntelligence,
                                                         SurveyDesignScore)
from xlsform_studio.app.workflow import Workflow
from xlsform_studio.models import (Choice, ChoiceList, FormSettings, Question,
                                   Questionnaire)


def _q(name, label, xlsform_type="text", **kw):
    return Question(name=name, label=label, xlsform_type=xlsform_type, **kw)


def _qn(questions, lists=None):
    qn = Questionnaire(settings=FormSettings(form_title="T", form_id="t",
                                             version="1"),
                       questions=questions)
    for cl in (lists or []):
        qn.add_choice_list(cl)
    return qn


def _score(questions, lists=None, **kw):
    return DesignIntelligence().score(_qn(questions, lists), **kw)


# --- overall shape -----------------------------------------------------------
def test_clean_short_form_scores_well():
    s = _score([_q("age", "Age", "integer", constraint=". >= 0"),
                _q("sex", "Sex", "select_one yn", list_name="yn")],
               [ChoiceList("yn", [Choice("m", "Male"), Choice("f", "Female")])])
    assert s.overall >= 80
    assert isinstance(s, SurveyDesignScore)
    # every dimension present; only objective_coverage unassessed by default
    names = {d.name for d in s.dimensions}
    assert len(names) == 10
    assert s.dimension("objective_coverage").assessed is False


# --- 1. question order -------------------------------------------------------
def test_sensitive_question_early_penalised():
    s = _score([_q("income", "What is your monthly income?", "integer"),
                _q("a", "Question A"), _q("b", "Question B"),
                _q("c", "Question C")])
    order = s.dimension("question_order")
    assert order.score < 100
    assert any("sensitive" in o for o in order.observations)


def test_sensitive_question_late_is_fine():
    s = _score([_q("a", "Question A"), _q("b", "Question B"),
                _q("c", "Question C"),
                _q("income", "What is your monthly income?", "integer")])
    assert s.dimension("question_order").score == 100


# --- 4. recall period consistency (signature) --------------------------------
def test_long_recall_window_flagged():
    s = _score([_q("v", "How many times in the last 5 years did you travel?",
                   "integer")])
    recall = s.dimension("recall_period_consistency")
    assert recall.score < 100
    assert any("recall bias" in o for o in recall.observations)


def test_bounded_recall_window_is_fine():
    s = _score([_q("v", "How many times in the last 7 days did you travel?",
                   "integer")])
    assert s.dimension("recall_period_consistency").score == 100


def test_many_distinct_recall_windows_flagged():
    s = _score([
        _q("a", "Visits in the last 7 days?", "integer"),
        _q("b", "Visits in the last month?", "integer"),
        _q("c", "Visits in the last 6 months?", "integer"),
        _q("d", "Visits in the last year?", "integer")])
    recall = s.dimension("recall_period_consistency")
    assert any("different recall windows" in o for o in recall.observations)


# --- 5. scale consistency ----------------------------------------------------
def test_mixed_point_count_scales_flagged():
    five = ChoiceList("agree5", [Choice("1", "Strongly agree"),
                                 Choice("2", "Agree"), Choice("3", "Neutral"),
                                 Choice("4", "Disagree"),
                                 Choice("5", "Strongly disagree")])
    four = ChoiceList("agree4", [Choice("1", "Strongly agree"),
                                 Choice("2", "Agree"), Choice("3", "Disagree"),
                                 Choice("4", "Strongly disagree")])
    s = _score([_q("q1", "I feel safe", "select_one agree5", list_name="agree5"),
                _q("q2", "I feel heard", "select_one agree4", list_name="agree4")],
               [five, four])
    scale = s.dimension("scale_consistency")
    assert scale.score < 100
    assert any("point counts" in o for o in scale.observations)


def test_mixed_scale_directions_flagged():
    """A normal (agree-first) and a reversed (disagree-first) Likert of the
    same family should be caught as running in both directions - the check
    that the 'agree' substring of 'disagree' used to silently defeat."""
    fwd = ChoiceList("af", [Choice("1", "Strongly agree"), Choice("2", "Agree"),
                            Choice("3", "Disagree"),
                            Choice("4", "Strongly disagree")])
    rev = ChoiceList("ar", [Choice("1", "Strongly disagree"),
                            Choice("2", "Disagree"), Choice("3", "Agree"),
                            Choice("4", "Strongly agree")])
    s = _score([_q("q1", "I feel safe", "select_one af", list_name="af"),
                _q("q2", "I feel heard", "select_one ar", list_name="ar")],
               [fwd, rev])
    scale = s.dimension("scale_consistency")
    assert any("both directions" in o for o in scale.observations)


# --- 9. redundancy -----------------------------------------------------------
def test_near_duplicate_questions_flagged():
    s = _score([_q("a", "How many children do you have living with you?"),
                _q("b", "How many children do you have living with you now?")])
    red = s.dimension("redundancy_detection")
    assert red.score < 100
    assert any("near-identical" in o for o in red.observations)


# --- 10. measurement validity ------------------------------------------------
def test_double_barreled_flagged():
    s = _score([_q("wsan", "Do you have access to clean water and sanitation?",
                   "select_one yn", list_name="yn")],
               [ChoiceList("yn", [Choice("y", "Yes"), Choice("n", "No")])])
    mv = s.dimension("measurement_validity")
    assert mv.score < 100
    assert any("double-barreled" in o for o in mv.observations)


def test_even_opinion_scale_without_neutral_flagged():
    four = ChoiceList("sat4", [Choice("1", "Very satisfied"),
                               Choice("2", "Satisfied"),
                               Choice("3", "Dissatisfied"),
                               Choice("4", "Very dissatisfied")])
    s = _score([_q("q", "How satisfied are you?", "select_one sat4",
                   list_name="sat4")], [four])
    assert any("neutral midpoint" in o
               for o in s.dimension("measurement_validity").observations)


# --- honesty layer -----------------------------------------------------------
def test_objective_coverage_not_assessed_without_objectives():
    d = _score([_q("a", "A")]).dimension("objective_coverage")
    assert d.assessed is False
    assert "not assessed" in d.basis


def test_objective_coverage_scored_from_matrix():
    matrix = ("# Coverage\n| Objective | Questions |\n| Water access | q1 |\n"
              "| Sanitation | (no question found - gap) |")
    d = _score([_q("q1", "Water source")],
               coverage_matrix=matrix).dimension("objective_coverage")
    assert d.assessed is True
    assert d.score < 100


def test_rating_gated_by_worst_dimension():
    # a form that is clean everywhere except a serious recall problem should
    # not be labelled publication-ready, even if the weighted mean is high
    s = _score([
        _q("smoke", "Have you ever smoked?", "select_one yn", list_name="yn"),
        _q("travel", "Have you ever traveled abroad in your life?",
           "select_one yn", list_name="yn"),
        _q("hosp", "Were you ever hospitalized in your lifetime?",
           "select_one yn", list_name="yn"),
        _q("age", "Age", "integer", constraint=". >= 0")],
        [ChoiceList("yn", [Choice("y", "Yes"), Choice("n", "No")])])
    assert s.dimension("recall_period_consistency").score < 70
    assert s.rating != "publication-ready"


# --- YAML tunability ---------------------------------------------------------
def test_vocab_falls_back_when_file_absent(tmp_path):
    # an empty dir has no design_intelligence.yaml; built-ins must carry it
    di = DesignIntelligence(vocab_dir=tmp_path)
    s = di.score(_qn([_q("income", "Your income?", "integer"),
                      _q("a", "A"), _q("b", "B"), _q("c", "C")]))
    assert s.dimension("question_order").score < 100


# --- workflow integration ----------------------------------------------------
def test_workflow_computes_and_writes_design_report(tmp_path):
    qn = _qn([_q("age", "Age", "integer", constraint=". >= 0"),
              _q("sex", "Sex", "select_one yn", list_name="yn")],
             [ChoiceList("yn", [Choice("m", "Male"), Choice("f", "Female")])])
    result = Workflow().run(qn, output_dir=tmp_path / "out",
                            write_outputs=True)
    assert result.design is not None
    assert result.design.overall > 0
    report = result.outputs["survey_design_report"]
    assert report.exists()
    assert "Survey Design Score" in report.read_text(encoding="utf-8")
    # and it appears in the QA report markdown (the PDF is rendered from this)
    from xlsform_studio.validation.report_generator import ReportGenerator
    qa = ReportGenerator().to_markdown(result.report, qn,
                                       quality=result.quality,
                                       duration=result.duration,
                                       design=result.design)
    assert "Survey Design Score" in qa
