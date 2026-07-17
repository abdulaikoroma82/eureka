"""Regression tests for the security / robustness hardening pass.

Each test pins a specific bug that was found by inspection and fixed:
formula injection in the exporter, the eager-pop label loss in
Question.from_dict, recursion/length DoS in the expression evaluator, the
variable-name length overflow, atomic version-history writes, the input
size guard, and the .xls/.md format handling.
"""

from __future__ import annotations

import io
import json

import openpyxl
import pytest

from xlsform_studio.app.artifacts import ArtifactBuilder
from xlsform_studio.models import (Choice, ChoiceList, FormSettings, Question,
                                   Questionnaire)
from xlsform_studio.parsers.factory import parse_file
from xlsform_studio.validation.expression_evaluator import (ExpressionEvaluator,
                                                            RuntimeEvaluator)
from xlsform_studio.xlsform.exporter import XLSFormExporter, _defuse


# --- C1: spreadsheet formula injection --------------------------------------
def _export_cell(qn, col_idx):
    wb = openpyxl.load_workbook(io.BytesIO(XLSFormExporter().export_bytes(qn)))
    return wb["survey"].cell(row=2, column=col_idx)


def test_formula_injection_in_label_is_neutralised():
    qn = Questionnaire(
        settings=FormSettings(form_title="T", form_id="t"),
        questions=[Question(name="q1", xlsform_type="text",
                            label='=HYPERLINK("http://evil","x")')])
    cell = _export_cell(qn, 3)                     # label column
    assert cell.data_type != "f"                   # not a live formula
    assert cell.value.startswith("'=")


def test_all_formula_leaders_defused_in_free_text():
    for lead in ("=", "+", "-", "@", "\t", "\r"):
        assert _defuse(f"{lead}danger", "label") == f"'{lead}danger"
    assert _defuse("safe", "label") == "safe"
    assert _defuse("", "label") == ""


def test_expression_columns_preserve_legitimate_unary_minus():
    # A calculation of -${x} must NOT be defused (it's valid XLSForm), but a
    # leading '=' is never valid there and still gets neutralised.
    assert _defuse("-${x}", "calculation") == "-${x}"
    assert _defuse("-1", "default") == "-1"
    assert _defuse("=cmd", "calculation") == "'=cmd"


# --- H1: Question.from_dict eager pop dropped the label ----------------------
def test_from_dict_keeps_explicit_label_alongside_question():
    q = Question.from_dict({"question": "Raw?", "label": "Polished",
                            "type": "text"})
    assert q.raw_label == "Raw?"
    assert q.label == "Polished"


def test_from_dict_label_only_still_populates_raw_label():
    q = Question.from_dict({"label": "Only a label", "type": "text"})
    assert q.raw_label == "Only a label"           # AI author keys off this


def test_from_dict_prefers_choices_over_raw_choices():
    q = Question.from_dict({"question": "Q?", "choices": ["Yes", "No"],
                            "raw_choices": ["A", "B"]})
    assert q.raw_choices == ["Yes", "No"]


# --- H2: recursion / length DoS in the evaluator ----------------------------
def test_deeply_nested_expression_does_not_crash():
    expr = "(" * 5000 + "1" + ")" * 5000
    assert RuntimeEvaluator().truthy(expr, {}, default=True) is True   # default
    assert ExpressionEvaluator().evaluate(expr, {}) is None


def test_overlong_expression_is_rejected_gracefully():
    expr = "1 + " * 5000 + "1"
    assert RuntimeEvaluator().truthy(expr, {}, default=False) is False
    # a normal expression still works
    assert RuntimeEvaluator().truthy("${a} >= 18", {"a": "20"}) is True


# --- H3: unique-name length overflow ----------------------------------------
def test_unique_name_never_exceeds_length_limit():
    from xlsform_studio.ai.form_author import AIFormAuthor
    author = AIFormAuthor.__new__(AIFormAuthor)
    author._max_name_length = 32
    used: set = set()
    base = "household_water_treatment_method_x"       # sanitises to 32 chars
    names = [author._unique_name(base, "", used) for _ in range(20)]
    assert all(len(n) <= 32 for n in names)
    assert len(set(names)) == 20                       # still unique


# --- M1: atomic version-history write ---------------------------------------
def test_version_history_survives_and_appends(tmp_path):
    b = ArtifactBuilder()
    qn = Questionnaire(settings=FormSettings(form_title="T", form_id="t",
                                             version="1"))
    path = tmp_path / "version_history.json"
    b.append_version_history(path, qn, "src", True, 0)
    b.append_version_history(path, qn, "src", True, 0)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data) == 2
    assert not list(tmp_path.glob("*.tmp"))            # temp file cleaned up


def test_version_history_recovers_from_corruption(tmp_path):
    path = tmp_path / "version_history.json"
    path.write_text("{ this is not valid json", encoding="utf-8")
    b = ArtifactBuilder()
    qn = Questionnaire(settings=FormSettings(form_id="t"))
    b.append_version_history(path, qn, "src", True, 0)
    assert len(json.loads(path.read_text(encoding="utf-8"))) == 1


# --- M2 / L1 / L2: input size guard and format handling ---------------------
def test_oversized_input_is_rejected(tmp_path, monkeypatch):
    import xlsform_studio.parsers.factory as factory
    monkeypatch.setattr(factory, "MAX_INPUT_BYTES", 100)
    big = tmp_path / "big.json"
    big.write_text('{"survey": []}' + " " * 500, encoding="utf-8")
    with pytest.raises(ValueError, match="above the"):
        parse_file(big)


def test_legacy_xls_is_no_longer_advertised():
    from xlsform_studio.app.config import SUPPORTED_INPUT_EXTENSIONS
    assert ".xls" not in SUPPORTED_INPUT_EXTENSIONS
    assert ".xlsx" in SUPPORTED_INPUT_EXTENSIONS


def test_unsupported_format_message_lists_md(tmp_path):
    f = tmp_path / "x.rtf"
    f.write_text("hi", encoding="utf-8")
    with pytest.raises(ValueError, match=r"\.md"):
        parse_file(f)
