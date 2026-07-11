"""Tests for the three gap-closure features: the assumptions verification
checklist, static path analysis (+ the tri-state expression evaluator), and
the choice-list semantic auditor."""

from __future__ import annotations

from xlsform_studio.app.verification_checklist import (
    ADVISORY, CRITICAL, INFO, VerificationChecklistBuilder)
from xlsform_studio.app.workflow import Workflow
from xlsform_studio.models import (Choice, ChoiceList, FormSettings,
                                   Question, Questionnaire)
from xlsform_studio.validation.choice_auditor import ChoiceAuditor
from xlsform_studio.validation.expression_evaluator import (
    EMPTY, ExpressionEvaluator)
from xlsform_studio.validation.path_analyzer import PathAnalyzer
from xlsform_studio.validation.report_generator import ReportGenerator
from xlsform_studio.validation.validator import Validator


# =============================================================================
# Feature 1: assumptions verification checklist
# =============================================================================
class TestVerificationChecklist:
    def _build(self, notes):
        qn = Questionnaire(settings=FormSettings(form_title="T", form_id="t"))
        return VerificationChecklistBuilder().build_markdown(qn, notes)

    def test_logic_resolution_is_critical(self):
        item = VerificationChecklistBuilder().classify(
            "[resident] Relevant compiled from logic: 'ask if yes'.")
        assert item.tier == CRITICAL
        assert "resident" in item.action

    def test_constraint_application_is_critical_with_population_action(self):
        item = VerificationChecklistBuilder().classify(
            "[age] Default 'integer' constraint applied.")
        assert item.tier == CRITICAL
        assert "population" in item.action

    def test_ai_cross_field_is_critical_and_mentions_original_vs_addition(self):
        item = VerificationChecklistBuilder().classify(
            "[end] AI-suggested cross-field constraint (ends after start). "
            "Original: `. != ''`. AI addition: `. > ${start}`. "
            "Please review before deployment.")
        assert item.tier == CRITICAL
        assert "original" in item.action.lower()
        assert "Original: `. != ''`" in item.assumption

    def test_ambiguous_type_is_critical(self):
        assert VerificationChecklistBuilder().classify(
            "[notes] No rule matched; defaulted to 'text'.").tier == CRITICAL

    def test_accepted_rename_is_critical(self):
        item = VerificationChecklistBuilder().classify(
            "[hh_size] AI-suggested variable name accepted: 'q7' -> "
            "'hh_size' (clarity); all references were updated.")
        assert item.tier == CRITICAL

    def test_translation_is_advisory(self):
        item = VerificationChecklistBuilder().classify(
            "[AI translation] Translated 12 label(s) to French.")
        assert item.tier == ADVISORY
        assert "native speaker" in item.action

    def test_choice_merge_is_advisory(self):
        assert VerificationChecklistBuilder().classify(
            "[choices] Choice list 'x' was identical to 'y' and was "
            "consolidated into it (same options).").tier == ADVISORY

    def test_keyword_match_is_informational(self):
        item = VerificationChecklistBuilder().classify(
            "[crops] Type 'select_multiple' inferred from keyword match.")
        assert item.tier == INFO
        assert item.action == ""

    def test_unknown_entries_land_in_advisory_not_info(self):
        item = VerificationChecklistBuilder().classify(
            "[x] A decision no rule has ever heard of.")
        assert item.tier == ADVISORY

    def test_markdown_has_counts_checkboxes_and_all_tiers(self):
        md = self._build([
            "[a] Relevant compiled from logic: 'if yes'.",
            "[AI translation] Translated 3 label(s) to French.",
            "[b] Type 'integer' inferred from keyword match.",
        ])
        assert "**1 critical**" in md and "**1 advisory**" in md \
            and "**1 informational**" in md
        assert md.count("- [ ]") == 3
        assert "Critical — Must Verify Before Deployment" in md
        assert "Advisory — Recommended Review" in md
        assert "Informational — No Action Needed" in md

    def test_every_note_classified_exactly_once(self):
        notes = [f"[q{i}] Note number {i}." for i in range(10)]
        md = self._build(notes)
        assert md.count("- [ ]") == len(notes)

    def test_artifact_written_in_output_package(self, tmp_path):
        qn = Questionnaire(
            settings=FormSettings(form_title="T", form_id="t"),
            questions=[Question(raw_label="How old are you?")])
        result = Workflow().run(qn, output_dir=tmp_path, write_outputs=True)
        path = result.outputs["assumptions_to_verify"]
        assert path.exists() and path.name == "assumptions_to_verify.md"
        text = path.read_text(encoding="utf-8")
        assert "critical" in text and "- [ ]" in text
        # Supplements, never replaces, the flat log.
        assert result.outputs["assumption_log"].exists()


# =============================================================================
# Feature 2a: the tri-state expression evaluator
# =============================================================================
class TestExpressionEvaluator:
    def setup_method(self):
        self.ev = ExpressionEvaluator()

    def test_equality_true_false_unknown(self):
        assert self.ev.evaluate("${r} = '1'", {"r": "1"}) is True
        assert self.ev.evaluate("${r} = '1'", {"r": "0"}) is False
        assert self.ev.evaluate("${r} = '1'", {}) is None

    def test_empty_value_semantics(self):
        assert self.ev.evaluate("${r} = '1'", {"r": EMPTY}) is False
        assert self.ev.evaluate("${r} = ''", {"r": EMPTY}) is True
        assert self.ev.evaluate("${r} != ''", {"r": EMPTY}) is False
        assert self.ev.evaluate("selected(${m}, 'x')", {"m": EMPTY}) is False

    def test_numeric_comparison_coerces_strings(self):
        assert self.ev.evaluate("${age} > 5", {"age": "12"}) is True
        assert self.ev.evaluate("${age} > 5", {"age": "3"}) is False
        assert self.ev.evaluate("${age} > 5", {"age": EMPTY}) is False

    def test_kleene_three_valued_logic(self):
        # False and unknown -> False; True or unknown -> True.
        assert self.ev.evaluate("${a} = '1' and ${b} = '2'", {"a": "0"}) is False
        assert self.ev.evaluate("${a} = '1' or ${b} = '2'", {"a": "1"}) is True
        assert self.ev.evaluate("${a} = '1' and ${b} = '2'", {"a": "1"}) is None

    def test_functions(self):
        assert self.ev.evaluate("not(${a} = '1')", {"a": "0"}) is True
        assert self.ev.evaluate("string-length(${n}) > 0", {"n": "ab"}) is True
        assert self.ev.evaluate("string-length(${n}) > 0", {"n": EMPTY}) is False
        assert self.ev.evaluate("selected(${m}, 'x')", {"m": "x y"}) is None
        assert self.ev.evaluate("today() > ${d}", {"d": "2000-01-01"}) is None
        assert self.ev.evaluate("count(${x}) > 0", {"x": "1"}) is None
        assert self.ev.evaluate("once(${x})", {"x": "1"}) is None

    def test_never_raises_on_garbage(self):
        assert self.ev.evaluate("garbage >< here", {}) is None
        assert self.ev.evaluate("", {}) is None
        assert self.ev.evaluate("((", {}) is None


# =============================================================================
# Feature 2b: static path analysis
# =============================================================================
def _yes_no():
    return {"yes_no": ChoiceList("yes_no", [Choice("1", "Yes"),
                                            Choice("0", "No")])}


class TestPathAnalyzer:
    def test_clean_form_produces_no_findings(self):
        qn = Questionnaire(questions=[
            Question(name="a", label="A", xlsform_type="integer")])
        assert PathAnalyzer().validate(qn) == []

    def test_error_calculation_over_definitely_empty_variable(self):
        qn = Questionnaire(
            questions=[
                Question(name="resident", label="Resident?", required=True,
                         xlsform_type="select_one yes_no", list_name="yes_no"),
                Question(name="years", label="Years", xlsform_type="integer",
                         required=True, relevant="${resident} = '1'"),
                Question(name="double_years", label="x",
                         xlsform_type="calculate",
                         calculation="${years} * 2"),
            ],
            choice_lists=_yes_no())
        findings = PathAnalyzer().validate(qn)
        errors = [f for f in findings if f.level == "error"]
        assert any("definitely empty" in f.message
                   and "double_years" in (f.location or "") for f in errors)

    def test_no_error_when_calculation_shares_the_guard(self):
        qn = Questionnaire(
            questions=[
                Question(name="resident", label="Resident?", required=True,
                         xlsform_type="select_one yes_no", list_name="yes_no"),
                Question(name="years", label="Years", xlsform_type="integer",
                         required=True, relevant="${resident} = '1'"),
                Question(name="double_years", label="x",
                         xlsform_type="calculate",
                         calculation="${years} * 2",
                         relevant="${resident} = '1'"),
            ],
            choice_lists=_yes_no())
        findings = PathAnalyzer().validate(qn)
        assert not any("definitely empty" in f.message for f in findings)

    def test_error_unreachable_question(self):
        qn = Questionnaire(
            questions=[
                Question(name="a", label="A?", required=True,
                         xlsform_type="select_one yes_no", list_name="yes_no"),
                Question(name="ghost_town", label="Never shown",
                         xlsform_type="text",
                         relevant="${a} = '1' and ${a} = '0'"),
            ],
            choice_lists=_yes_no())
        findings = PathAnalyzer().validate(qn)
        assert any(f.level == "error" and "unreachable" in f.message
                   for f in findings)

    def test_error_reference_to_nonexistent_variable(self):
        qn = Questionnaire(questions=[
            Question(name="a", label="A", xlsform_type="integer",
                     constraint=". < ${ghost}")])
        findings = PathAnalyzer().validate(qn)
        assert any(f.level == "error"
                   and "does not exist anywhere" in f.message
                   for f in findings)

    def test_error_inner_repeat_variable_referenced_outside(self):
        qn = Questionnaire(questions=[
            Question(name="children", label="Children",
                     xlsform_type="begin repeat"),
            Question(name="child_age", label="Age", xlsform_type="integer",
                     required=True),
            Question(name="children_end", xlsform_type="end repeat"),
            Question(name="oldest", label="x", xlsform_type="calculate",
                     calculation="${child_age} + 1"),
        ])
        findings = PathAnalyzer().validate(qn)
        assert any(f.level == "error" and "repeat" in f.message
                   and "oldest" in (f.location or "") for f in findings)

    def test_outer_repeat_variable_visible_inside_nested_repeat(self):
        qn = Questionnaire(questions=[
            Question(name="hh", label="Household", xlsform_type="begin repeat"),
            Question(name="hh_id", label="ID", xlsform_type="text",
                     required=True),
            Question(name="members", label="Members",
                     xlsform_type="begin repeat"),
            Question(name="member_code", label="x", xlsform_type="calculate",
                     calculation="${hh_id}"),
            Question(name="members_end", xlsform_type="end repeat"),
            Question(name="hh_end", xlsform_type="end repeat"),
        ])
        findings = PathAnalyzer().validate(qn)
        assert not any("repeat" in f.message and f.level == "error"
                       for f in findings)

    def test_warning_possibly_filled_reference(self):
        qn = Questionnaire(questions=[
            Question(name="notes", label="Notes", xlsform_type="text"),
            Question(name="echo", label="x", xlsform_type="calculate",
                     calculation="${notes}"),
        ])
        findings = PathAnalyzer().validate(qn)
        assert any(f.level == "warning" and "possibly filled" in f.message
                   for f in findings)

    def test_warning_required_question_with_relevant(self):
        qn = Questionnaire(
            questions=[
                Question(name="a", label="A?", required=True,
                         xlsform_type="select_one yes_no", list_name="yes_no"),
                Question(name="b", label="B", xlsform_type="integer",
                         required=True, relevant="${a} = '1'"),
            ],
            choice_lists=_yes_no())
        findings = PathAnalyzer().validate(qn)
        assert any(f.level == "warning"
                   and "required rule never fires" in f.message
                   and f.location == "b" for f in findings)

    def test_warning_near_dead_question(self):
        five = {"c5": ChoiceList("c5", [Choice(str(i), f"C{i}")
                                        for i in range(1, 6)])}
        qn = Questionnaire(
            questions=[
                Question(name="a", label="A", required=True,
                         xlsform_type="select_one c5", list_name="c5"),
                Question(name="b", label="B", required=True,
                         xlsform_type="select_one c5", list_name="c5"),
                # Shown on 1 of 25 paths = 4% < 5%.
                Question(name="rare", label="Rare", xlsform_type="text",
                         relevant="${a} = '1' and ${b} = '1'"),
            ],
            choice_lists=five)
        findings = PathAnalyzer().validate(qn)
        assert any("near-dead" in f.message and f.location == "rare"
                   for f in findings)

    def test_path_explosion_falls_back_to_conservative_mode(self):
        # 14 required yes/no selects, each referenced -> 2^14 = 16,384 paths.
        questions = []
        for i in range(14):
            questions.append(Question(
                name=f"d{i}", label=f"D{i}", required=True,
                xlsform_type="select_one yes_no", list_name="yes_no"))
            questions.append(Question(
                name=f"f{i}", label=f"F{i}", xlsform_type="text",
                relevant=f"${{d{i}}} = '1'"))
        qn = Questionnaire(questions=questions, choice_lists=_yes_no())
        analyzer = PathAnalyzer()
        findings = analyzer.validate(qn)
        assert analyzer.approximated
        assert any("conservative approximation" in f.message
                   for f in findings)

    def test_group_relevance_gates_members(self):
        # The group's condition is conjoined onto members: on the path
        # where the group is hidden, its member is definitely empty.
        qn = Questionnaire(
            questions=[
                Question(name="has_farm", label="Farm?", required=True,
                         xlsform_type="select_one yes_no", list_name="yes_no"),
                Question(name="farm", label="Farm", xlsform_type="begin group",
                         relevant="${has_farm} = '1'"),
                Question(name="hectares", label="Ha", xlsform_type="decimal",
                         required=True),
                Question(name="farm_end", xlsform_type="end group"),
                Question(name="tax", label="x", xlsform_type="calculate",
                         calculation="${hectares} * 100"),
            ],
            choice_lists=_yes_no())
        findings = PathAnalyzer().validate(qn)
        assert any(f.level == "error" and "definitely empty" in f.message
                   and f.location == "tax" for f in findings)

    def test_validator_flag_disables_path_analysis(self):
        qn = Questionnaire(questions=[
            Question(name="a", label="A", xlsform_type="integer",
                     constraint=". < ${ghost}")])
        on = Validator(deep=False).validate(qn)
        off = Validator(deep=False).validate(qn, path_analysis=False)
        assert any(f.category == "path_analysis" for f in on.findings)
        assert not any(f.category == "path_analysis" for f in off.findings)


# =============================================================================
# Feature 3: choice list semantic auditor
# =============================================================================
def _list_only_form(name, choices):
    """A form whose single select_one uses the list under test."""
    return Questionnaire(
        questions=[Question(name="q", label="Q?",
                            xlsform_type=f"select_one {name}",
                            list_name=name)],
        choice_lists={name: ChoiceList(name, choices)})


class TestChoiceAuditor:
    def test_likert_scale_missing_midpoint(self):
        qn = _list_only_form("rating", [
            Choice("1", "Very good"), Choice("2", "Good"),
            Choice("3", "Poor"), Choice("4", "Very poor")])
        findings = ChoiceAuditor().validate(qn)
        hit = [f for f in findings if "Fair" in f.message]
        assert hit and hit[0].level == "warning"

    def test_complete_scale_not_flagged(self):
        qn = _list_only_form("rating", [
            Choice("1", "Very good"), Choice("2", "Good"), Choice("3", "Fair"),
            Choice("4", "Poor"), Choice("5", "Very poor")])
        assert not [f for f in ChoiceAuditor().validate(qn)
                    if "skips intermediate" in f.message]

    def test_weekday_order_violation(self):
        qn = _list_only_form("days", [
            Choice("wed", "Wednesday"), Choice("mon", "Monday"),
            Choice("tue", "Tuesday")])
        findings = ChoiceAuditor().validate(qn)
        assert any("logical order" in f.message for f in findings)

    def test_sunday_first_week_is_accepted_rotation(self):
        qn = _list_only_form("days", [
            Choice("sun", "Sunday"), Choice("mon", "Monday"),
            Choice("tue", "Tuesday"), Choice("wed", "Wednesday")])
        assert not [f for f in ChoiceAuditor().validate(qn)
                    if "logical order" in f.message]

    def test_size_order_violation(self):
        qn = _list_only_form("sizes", [
            Choice("m", "Medium"), Choice("s", "Small"), Choice("l", "Large")])
        findings = ChoiceAuditor().validate(qn)
        assert any("logical order" in f.message
                   and "Small, Medium, Large" in f.message for f in findings)

    def test_numeric_range_labels_out_of_order(self):
        qn = _list_only_form("ranges", [
            Choice("b", "6-10 years"), Choice("a", "1-5 years"),
            Choice("c", "11-15 years")])
        findings = ChoiceAuditor().validate(qn)
        assert any("ascending order" in f.message for f in findings)

    def test_other_without_specify_is_error(self):
        qn = _list_only_form("src", [
            Choice("piped", "Piped"), Choice("other", "Other")])
        findings = ChoiceAuditor().validate(qn)
        hit = [f for f in findings if "specify" in f.message.lower()
               or "follow-up" in f.message]
        assert hit and hit[0].level == "error"

    def test_other_with_specify_is_clean(self):
        qn = _list_only_form("src", [
            Choice("piped", "Piped"), Choice("other", "Other")])
        qn.questions.append(Question(
            name="q_other", label="Please specify", xlsform_type="text",
            relevant="selected(${q}, 'other')"))
        assert not [f for f in ChoiceAuditor().validate(qn)
                    if f.level == "error"]

    def test_or_other_without_explicit_other_is_warning(self):
        qn = Questionnaire(
            questions=[Question(name="q", label="Q?",
                                xlsform_type="select_one src or_other",
                                list_name="src")],
            choice_lists={"src": ChoiceList("src", [
                Choice("piped", "Piped"), Choice("well", "Well")])})
        findings = ChoiceAuditor().validate(qn)
        hit = [f for f in findings if "or_other" in f.message]
        assert hit and hit[0].level == "warning"

    def test_gapped_codes_flagged_sequential_and_binary_not(self):
        gapped = _list_only_form("g", [
            Choice("1", "Maize"), Choice("3", "Rice"), Choice("5", "Wheat")])
        assert any("non-sequential codes" in f.message
                   for f in ChoiceAuditor().validate(gapped))

        sequential = _list_only_form("s", [
            Choice("1", "Maize"), Choice("2", "Rice"), Choice("3", "Wheat")])
        assert not [f for f in ChoiceAuditor().validate(sequential)
                    if "non-sequential" in f.message]

        yes_no = _list_only_form("yn", [Choice("1", "Yes"), Choice("0", "No")])
        assert not [f for f in ChoiceAuditor().validate(yes_no)
                    if "non-sequential" in f.message]

    def test_sentinel_outlier_flagged(self):
        qn = _list_only_form("lvl", [
            Choice("1", "None"), Choice("2", "Primary"),
            Choice("3", "Secondary"), Choice("99", "Don't know")])
        findings = ChoiceAuditor().validate(qn)
        assert any("outlier 99" in f.message for f in findings)

    def test_wired_into_validator_and_report_sections(self):
        qn = Questionnaire(
            settings=FormSettings(form_title="T", form_id="t"),
            questions=[
                Question(name="q", label="Q?", xlsform_type="select_one days",
                         list_name="days"),
                Question(name="calcq", label="x", xlsform_type="calculate",
                         calculation="${ghost} + 1"),
            ],
            choice_lists={"days": ChoiceList("days", [
                Choice("wed", "Wednesday"), Choice("mon", "Monday"),
                Choice("tue", "Tuesday")])})
        report = Validator(deep=False).validate(qn)
        md = ReportGenerator().to_markdown(report, qn)
        assert "## Choice List Quality" in md
        assert "## Path Analysis" in md
