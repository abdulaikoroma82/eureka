"""Tests for the interview simulator: the concrete runtime evaluator, the
Interview engine (skips, constraints, calculations, single & nested
repeats), and the CLI --simulate driver."""

from __future__ import annotations

import io

from xlsform_studio.app.main import run_simulation
from xlsform_studio.app.simulator import Interview
from xlsform_studio.models import (Choice, ChoiceList, FormSettings, Question,
                                   Questionnaire)
from xlsform_studio.validation.expression_evaluator import (EMPTY,
                                                            ExpressionEvaluator,
                                                            RuntimeEvaluator)


def _yn():
    return {"yes_no": ChoiceList("yes_no", [Choice("1", "Yes"),
                                            Choice("0", "No")])}


# =============================================================================
# Runtime evaluator (concrete)
# =============================================================================
class TestRuntimeEvaluator:
    def setup_method(self):
        self.r = RuntimeEvaluator()

    def test_relevance_is_concrete(self):
        assert self.r.truthy("${a} = '1'", {"a": "1"}) is True
        assert self.r.truthy("${a} = '1'", {"a": "0"}) is False
        assert self.r.truthy("${a} = '1'", {}) is False        # missing = blank
        assert self.r.truthy("", {}) is True                   # no relevant = shown

    def test_selected_and_count_on_concrete_multiselect(self):
        assert self.r.truthy("selected(${m}, 'x')", {"m": "x y"}) is True
        assert self.r.truthy("selected(${m}, 'z')", {"m": "x y"}) is False
        assert self.r.compute("count-selected(${m})", {"m": "x y z"}) == "3"

    def test_arithmetic_and_functions(self):
        assert self.r.compute("${a} * 2", {"a": "12"}) == "24"
        assert self.r.compute("${a} + ${b}", {"a": "3", "b": "4"}) == "7"
        assert self.r.compute("round(${x} div 3, 2)", {"x": "10"}) == "3.33"
        assert self.r.compute("if(${age} > 17, 'adult', 'minor')",
                              {"age": "20"}) == "adult"
        assert self.r.compute("int(${x} div 2)", {"x": "7"}) == "3"

    def test_self_and_date_relationals(self):
        import datetime
        assert self.r.truthy(". >= 0 and . <= 120", {}, self_value="45") is True
        assert self.r.truthy(". >= 0 and . <= 120", {}, self_value="200") is False
        past = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        future = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        assert self.r.truthy(". <= today()", {}, self_value=past) is True
        assert self.r.truthy(". <= today()", {}, self_value=future) is False
        assert self.r.truthy(". >= ${start}", {"start": "2026-01-01"},
                             self_value="2026-02-01") is True

    def test_unparseable_is_blank_not_error(self):
        assert self.r.compute("garbage >< nonsense", {}) == ""
        assert self.r.truthy("((", {}, default=True) is True

    def test_static_evaluator_unchanged(self):
        """The refactor must not alter the tri-state evaluator the path
        analyzer depends on."""
        s = ExpressionEvaluator()
        assert s.evaluate("${a} = '1'", {"a": "1"}) is True
        assert s.evaluate("${a} = '1'", {"a": EMPTY}) is False
        assert s.evaluate("${a} = '1'", {}) is None            # unknown
        assert s.evaluate("selected(${m}, 'x')", {"m": "x y"}) is None
        assert s.evaluate(". <= today()", {}) is None


# =============================================================================
# Interview engine
# =============================================================================
class TestInterviewEngine:
    def _skip_form(self):
        return Questionnaire(
            settings=FormSettings(form_title="T", form_id="t"),
            questions=[
                Question(name="resident", label="Resident?", required=True,
                         xlsform_type="select_one yes_no", list_name="yes_no"),
                Question(name="years", label="Years here", required=True,
                         xlsform_type="integer", relevant="${resident} = '1'",
                         constraint=". >= 0 and . <= 120",
                         constraint_message="0-120 only."),
                Question(name="status", label="Status", xlsform_type="calculate",
                         calculation="if(${resident} = '1', 'local', 'visitor')"),
                Question(name="comment", label="Comment", xlsform_type="text"),
            ],
            choice_lists=_yn())

    def test_relevant_shows_and_hides(self):
        sim = self._skip_form()
        iv = Interview(sim)
        assert iv.current().question.name == "resident"
        iv.submit("1")
        assert iv.current().question.name == "years"          # shown

        iv2 = Interview(sim)
        iv2.submit("0")
        assert iv2.current().question.name == "comment"       # years hidden
        assert "years" in {a.name for a in iv2.state().skipped}

    def test_constraint_rejects_then_accepts(self):
        iv = Interview(self._skip_form())
        iv.submit("1")
        bad = iv.submit("999")
        assert not bad.ok and "0-120" in bad.error
        assert iv.current().question.name == "years"          # unchanged
        assert iv.submit("5").ok

    def test_required_blank_rejected(self):
        iv = Interview(self._skip_form())
        r = iv.submit("")
        assert not r.ok and "required" in r.error.lower()

    def test_invalid_choice_rejected(self):
        iv = Interview(self._skip_form())
        r = iv.submit("maybe")
        assert not r.ok and "not an option" in r.error

    def test_calculation_updates_live(self):
        iv = Interview(self._skip_form())
        iv.submit("1")
        iv.submit("5")
        calcs = {c.name: c.value for c in iv.state().calculations}
        assert calcs["status"] == "local"

        iv2 = Interview(self._skip_form())
        iv2.submit("0")
        calcs2 = {c.name: c.value for c in iv2.state().calculations}
        assert calcs2["status"] == "visitor"

    def test_interview_completes(self):
        iv = Interview(self._skip_form())
        iv.submit("1")
        iv.submit("5")
        iv.submit("")                                         # optional comment
        assert iv.current().kind == "done"
        assert iv.state().done

    def test_choice_labels_in_event_log(self):
        iv = Interview(self._skip_form())
        iv.submit("1")
        answered = [e for e in iv.state().events if e.kind == "answered"]
        assert any(e.detail == "Yes" for e in answered)


class TestRepeats:
    def _roster(self):
        return Questionnaire(
            questions=[
                Question(name="hh_name", label="Household", required=True,
                         xlsform_type="text"),
                Question(name="person", label="Person", required=True,
                         xlsform_type="text", section="Members",
                         section_type="repeat"),
                Question(name="age", label="Age", required=True,
                         xlsform_type="integer", section="Members",
                         section_type="repeat",
                         constraint=". >= 0 and . <= 120",
                         constraint_message="0-120."),
                Question(name="is_adult", label="Adult?", xlsform_type="calculate",
                         section="Members", section_type="repeat",
                         calculation="if(${age} >= 18, 'yes', 'no')"),
            ])

    def test_single_repeat_two_instances_with_per_instance_calc(self):
        iv = Interview(self._roster())
        iv.submit("Kamara")
        assert iv.current().question.name == "person"
        iv.submit("Aminata")
        iv.submit("30")
        assert {c.name: c.value for c in iv.state().calculations}["is_adult"] == "yes"

        step = iv.current()
        assert step.kind == "repeat_prompt" and step.completed_instances == 1
        iv.add_repeat_instance()
        assert iv.current().path == "Members 2"
        iv.submit("Sia")
        iv.submit("10")
        assert {c.name: c.value for c in iv.state().calculations}["is_adult"] == "no"
        iv.finish_repeat()
        assert iv.current().kind == "done"

    def test_repeat_constraint_scopes_to_instance(self):
        iv = Interview(self._roster())
        iv.submit("HH")
        iv.submit("A")
        bad = iv.submit("500")
        assert not bad.ok and "0-120" in bad.error

    def test_nested_structural_repeats(self):
        qn = Questionnaire(questions=[
            Question(name="hh", xlsform_type="begin repeat", label="Household"),
            Question(name="hh_id", label="HH id", required=True, xlsform_type="text"),
            Question(name="members", xlsform_type="begin repeat", label="Member"),
            Question(name="mname", label="Member name", required=True,
                     xlsform_type="text"),
            Question(name="link", label="Link", xlsform_type="calculate",
                     calculation="if(${hh_id} = 'H1', 'first', 'other')"),
            Question(name="members_end", xlsform_type="end repeat"),
            Question(name="hh_end", xlsform_type="end repeat"),
        ])
        iv = Interview(qn)
        iv.submit("H1")
        assert iv.current().path == "Household 1 › Member 1"
        iv.submit("Aminata")
        assert {c.name: c.value for c in iv.state().calculations}["link"] == "first"
        assert iv.current().repeat_label == "Member"           # inner prompt
        iv.finish_repeat()                                     # close Member
        assert iv.current().repeat_label == "Household"        # outer prompt
        iv.add_repeat_instance()                               # 2nd household
        assert iv.current().path == "Household 2"
        iv.submit("H2")
        iv.submit("Sia")
        assert {c.name: c.value for c in iv.state().calculations}["link"] == "other"
        iv.finish_repeat()
        iv.finish_repeat()
        assert iv.current().kind == "done"

    def test_irrelevant_repeat_skipped_whole(self):
        qn = Questionnaire(questions=[
            Question(name="has_kids", label="Has children?", required=True,
                     xlsform_type="select_one yes_no", list_name="yes_no"),
            Question(name="kids", xlsform_type="begin repeat", label="Child",
                     relevant="${has_kids} = '1'"),
            Question(name="kid_name", label="Child name", required=True,
                     xlsform_type="text"),
            Question(name="kids_end", xlsform_type="end repeat"),
            Question(name="done_q", label="Anything else?", xlsform_type="text"),
        ], choice_lists=_yn())
        iv = Interview(qn)
        iv.submit("0")                                        # no children
        assert iv.current().question.name == "done_q"         # repeat skipped

    def test_restart_resets(self):
        iv = Interview(self._roster())
        iv.submit("HH")
        iv.restart()
        assert iv.current().question.name == "hh_name"
        assert iv.state().answered == []


# =============================================================================
# CLI --simulate driver
# =============================================================================
class TestSimulateCLI:
    def test_scripted_interview_runs_to_completion(self):
        qn = Questionnaire(
            settings=FormSettings(form_title="T", form_id="t"),
            questions=[
                Question(name="resident", label="Resident?", required=True,
                         xlsform_type="select_one yes_no", list_name="yes_no"),
                Question(name="years", label="Years", required=True,
                         xlsform_type="integer", relevant="${resident} = '1'",
                         constraint=". >= 0 and . <= 120",
                         constraint_message="0-120 only."),
                Question(name="status", label="Status", xlsform_type="calculate",
                         calculation="if(${resident} = '1', 'local', 'visitor')"),
            ],
            choice_lists=_yn())
        answers = iter(["1", "999", "5"])                     # 999 is rejected
        out = io.StringIO()
        run_simulation(qn, input_fn=lambda *_: next(answers), out=out)
        text = out.getvalue()
        assert "Interview complete" in text
        assert "0-120 only." in text                          # rejection echoed
        assert "status=local" in text                         # live calc echoed
        assert "resident = 1" in text and "years = 5" in text

    def test_quit_exits_cleanly(self):
        qn = Questionnaire(
            questions=[Question(name="a", label="A", xlsform_type="text")])
        out = io.StringIO()
        run_simulation(qn, input_fn=lambda *_: "q", out=out)
        assert "Simulation ended." in out.getvalue()

    def test_repeat_prompt_scripted(self):
        qn = Questionnaire(questions=[
            Question(name="person", label="Person", required=True,
                     xlsform_type="text", section="People", section_type="repeat"),
        ])
        # person=Aa, add another -> person=Bb, done
        answers = iter(["Aa", "y", "Bb", "n"])
        out = io.StringIO()
        run_simulation(qn, input_fn=lambda *_: next(answers), out=out)
        text = out.getvalue()
        assert "Interview complete" in text
        assert "Answered 2" in text
