"""Tests for round-trip editing: export an XLSForm, edit it, re-import it
without losing per-field confidence or the assumptions log.

Covers the three new pieces:

* the provenance sidecar (:mod:`xlsform_studio.app.provenance`) - a faithful
  write/read cycle of the whole model, decisions included;
* the reconciler (:mod:`xlsform_studio.app.roundtrip`) - carry confidence for
  unchanged fields, stamp human review for changed ones, flag new questions;
* :meth:`Workflow.run_roundtrip` end-to-end, with a real XLSForm exported,
  edited and re-imported, and no API key anywhere in sight.
"""

from __future__ import annotations

from xlsform_studio.app.provenance import (SIDECAR_SUFFIX, model_to_snapshot,
                                           read_model_sidecar,
                                           snapshot_to_model,
                                           write_model_sidecar)
from xlsform_studio.app.roundtrip import reconcile
from xlsform_studio.app.workflow import Workflow
from xlsform_studio.models import (Choice, ChoiceList, FormSettings, Question,
                                   Questionnaire)
from xlsform_studio.parsers.factory import parse_file
from xlsform_studio.xlsform.exporter import XLSFormExporter


def _prior() -> Questionnaire:
    """A small authored form carrying confidence + assumptions, as a real
    run would leave it."""
    age = Question(name="age", label="Age", xlsform_type="integer",
                   constraint=". >= 0 and . <= 120", section="Household")
    age.add_decision("type", "integer", "high", "[age] Numeric from keyword.")
    age.add_decision("constraint", ". >= 0 and . <= 120", "medium",
                     "[age] Default integer bounds applied.")
    adult = Question(name="adult", label="Adult?",
                     xlsform_type="select_one yes_no", list_name="yes_no",
                     relevant="${age} >= 18", section="Household")
    adult.add_decision("type", "select_one yes_no", "high",
                       "[adult] Yes/No detected.")
    adult.add_decision("relevant", "${age} >= 18", "medium",
                       "[adult] Skip logic compiled from 'ask if adult'.")
    qn = Questionnaire(
        settings=FormSettings(form_title="Household", form_id="household"),
        questions=[age, adult])
    yn = ChoiceList(list_name="yes_no",
                    choices=[Choice("yes", "Yes"), Choice("no", "No")])
    qn.add_choice_list(yn)
    return qn


# --- provenance sidecar ------------------------------------------------------
def test_sidecar_round_trips_decisions_and_assumptions(tmp_path):
    qn = _prior()
    path = write_model_sidecar(qn, tmp_path / f"household{SIDECAR_SUFFIX}")
    loaded = read_model_sidecar(path)

    assert [q.name for q in loaded.questions] == ["age", "adult"]
    age = loaded.questions[0]
    assert age.xlsform_type == "integer"
    assert age.constraint == ". >= 0 and . <= 120"
    # confidence + reasons survived the write/read cycle
    assert [(d.field_name, d.confidence) for d in age.decisions] == [
        ("type", "high"), ("constraint", "medium")]
    assert any("Numeric from keyword" in a for a in age.assumptions)
    # choice list + settings intact
    assert loaded.choice_lists["yes_no"].choice_names() == ["yes", "no"]
    assert loaded.settings.form_id == "household"


def test_snapshot_preserves_extra_passthrough_columns(tmp_path):
    q = Question(name="q1", label="Q1", xlsform_type="text")
    q.extra["label::French (fr)"] = "Q1 en francais"
    qn = Questionnaire(settings=FormSettings(form_id="f"), questions=[q])
    loaded = snapshot_to_model(model_to_snapshot(qn))
    assert loaded.questions[0].extra["label::French (fr)"] == "Q1 en francais"


def test_read_sidecar_rejects_foreign_json(tmp_path):
    bad = tmp_path / "not_a_model.json"
    bad.write_text('{"hello": "world"}', encoding="utf-8")
    try:
        read_model_sidecar(bad)
    except ValueError as exc:
        assert "model snapshot" in str(exc)
    else:  # pragma: no cover - guard
        raise AssertionError("expected ValueError for a non-snapshot file")


# --- reconcile ---------------------------------------------------------------
def test_reconcile_carries_confidence_for_unchanged_fields():
    prior = _prior()
    edited = _prior()          # identical parse, nothing touched
    # a re-parsed XLSForm has no decisions of its own
    for q in edited.questions:
        q.decisions = []
        q.assumptions = []

    merged, notes = reconcile(edited, prior)

    age = merged.questions[0]
    # original decisions were carried forward, not lost
    assert [(d.field_name, d.confidence) for d in age.decisions] == [
        ("type", "high"), ("constraint", "medium")]
    assert any("carried forward" in n for n in notes)


def test_reconcile_stamps_human_review_for_changed_field():
    prior = _prior()
    edited = _prior()
    for q in edited.questions:
        q.decisions = []
        q.assumptions = []
    edited.questions[0].label = "Age in completed years"   # a human edit

    merged, notes = reconcile(edited, prior)

    age = merged.questions[0]
    latest = age.decisions[-1]
    assert latest.field_name == "label"
    assert latest.confidence == "high"
    assert "reviewed by a human" in latest.reason
    assert any("Label edited" in n for n in notes)


def test_reconcile_flags_new_question_low_confidence():
    prior = _prior()
    edited = _prior()
    for q in edited.questions:
        q.decisions = []
    edited.questions.append(
        Question(name="income", label="Monthly income", xlsform_type="decimal"))

    merged, notes = reconcile(edited, prior)

    income = merged.questions[-1]
    assert income.decisions[-1].confidence == "low"
    assert any("New question introduced" in n for n in notes)


def test_reconcile_detects_rename_and_carries_provenance():
    prior = _prior()
    edited = _prior()
    for q in edited.questions:
        q.decisions = []
        q.assumptions = []
    # 'age' renamed to 'age_years' (same label) - a rename, not delete+add.
    edited.questions[0].name = "age_years"

    merged, notes = reconcile(edited, prior)

    renamed = next(q for q in merged.questions if q.name == "age_years")
    # the original type/constraint confidence transferred to the new name
    assert any(d.field_name == "type" and d.confidence == "high"
               for d in renamed.decisions)
    # and the rename itself is a high-confidence human decision
    assert any(d.field_name == "name" and d.confidence == "high"
               and "age" in d.reason for d in renamed.decisions)
    assert any("Renamed from 'age'" in n for n in notes)
    # not misreported as an add or a removal
    assert not any("New question introduced" in n for n in notes)
    assert not any("removed in the re-imported" in n for n in notes)


def test_reconcile_name_match_wins_over_label_rename():
    """An exact name-match must never be stolen by a rename-by-label, even
    when another question shares the label."""
    prior = _prior()
    # give 'adult' the same label as 'age' to bait the rename heuristic
    prior.questions[1].label = "Age"
    edited = _prior()
    edited.questions[1].label = "Age"
    for q in edited.questions:
        q.decisions = []
    edited.questions[0].name = "age_years"      # genuine rename of 'age'

    merged, notes = reconcile(edited, prior)

    # 'adult' matched by name and survived; the rename resolved to 'age'
    assert any("Renamed from 'age'" in n for n in notes)
    assert not any("removed in the re-imported" in n for n in notes)


def test_reconcile_logs_removed_question():
    prior = _prior()
    edited = _prior()
    edited.questions = [edited.questions[0]]   # 'adult' deleted in the edit

    _, notes = reconcile(edited, prior)
    assert any("removed in the re-imported XLSForm" in n for n in notes)


# --- Workflow.run_roundtrip (end to end, no API key) -------------------------
def test_run_roundtrip_preserves_and_rebuilds(tmp_path):
    prior = _prior()
    sidecar = write_model_sidecar(prior, tmp_path / f"household{SIDECAR_SUFFIX}")
    XLSFormExporter().export(prior, tmp_path / "household.xlsx")

    # Simulate an out-of-band edit: re-parse the exported form, change one
    # label, and write it back out as the "edited" workbook.
    edited = parse_file(tmp_path / "household.xlsx")
    edited_age = next(q for q in edited.questions if q.name == "age")
    edited_age.label = "Age in completed years"
    edited_path = XLSFormExporter().export(edited, tmp_path / "household_edited.xlsx")

    # No ai_client is supplied anywhere - round-trip must not need one.
    result = Workflow().run_roundtrip(
        edited_path, sidecar, output_dir=tmp_path / "out", write_outputs=True)

    ages = [q for q in result.questionnaire.questions if q.name == "age"]
    adults = [q for q in result.questionnaire.questions if q.name == "adult"]
    assert ages and adults
    # untouched question kept its original confidence
    assert any(d.field_name == "type" and d.confidence == "high"
               for d in adults[0].decisions)
    # edited question gained a high-confidence human-review decision
    assert any(d.field_name == "label" and d.confidence == "high"
               for d in ages[0].decisions)
    # the full package rebuilt, including a fresh sidecar
    assert result.outputs["model_snapshot"].exists()
    assert result.outputs["enumerator_guide"].exists()
    # the edit shows up in the reconciliation notes / assumption log
    assert any("Label edited" in a for a in result.assumptions)


def test_run_roundtrip_accepts_a_questionnaire_as_prior(tmp_path):
    prior = _prior()
    XLSFormExporter().export(prior, tmp_path / "household.xlsx")
    result = Workflow().run_roundtrip(
        tmp_path / "household.xlsx", prior,
        output_dir=tmp_path / "out", write_outputs=False)
    assert result.questionnaire.settings.form_id == "household"


def test_every_run_writes_a_model_sidecar(tmp_path):
    """The sidecar is what makes a later round-trip possible, so it must be
    part of every output package, not opt-in."""
    prior = _prior()
    result = Workflow().run(prior, output_dir=tmp_path / "out",
                            write_outputs=True)
    snap = result.outputs["model_snapshot"]
    assert snap.exists() and snap.name.endswith(SIDECAR_SUFFIX)
    # and it reloads
    assert read_model_sidecar(snap).settings.form_id == "household"
