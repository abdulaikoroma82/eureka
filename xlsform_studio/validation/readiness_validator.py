"""Deployment readiness validator (deterministic; Module D10).

Purpose
-------
Catch the gaps that don't break *compilation* but break *field work*: a
form can be structurally perfect and still deploy half-translated, missing
its media files, or unusable on a low-end device. Everything here is a
set/count property of the compiled form - enumerable and exactly
decidable, so it belongs to the rule layer.

Checks
------
* **Translation completeness** (warning): for every translation column the
  form declares anywhere (``label::French (fr)``, ``hint::…``), every
  translatable item must carry it - a half-translated form silently shows
  enumerators a mix of languages. Reports exactly which items are missing.
* **Default language** (warning): forms with translation columns should
  declare ``default_language``, otherwise platforms guess.
* **Media manifest** (info): every file referenced by ``media::…`` columns
  is listed, as a packing reminder - the workbook does not contain the
  files, they must be uploaded with it. Empty media references are flagged
  (warning).
* **Device compatibility** (warning/info): very long choice lists without
  a search/autocomplete appearance stall low-end devices; very large forms
  slow load times.
* **Version metadata** (info): a missing ``version`` makes round-to-round
  form management guesswork.

Inputs
------
A compiled :class:`~xlsform_studio.models.Questionnaire`.

Outputs
-------
A list of :class:`~xlsform_studio.validation.report_generator.Finding`
with category ``"readiness"``.

Example
-------
>>> from xlsform_studio.models import Questionnaire, Question, FormSettings
>>> qn = Questionnaire(settings=FormSettings(form_title="T", form_id="t"),
...     questions=[Question(name="a", label="A", xlsform_type="text",
...                         extra={"label::French (fr)": "A (fr)"}),
...                Question(name="b", label="B", xlsform_type="text")])
>>> any("French" in f.message for f in ReadinessValidator().validate(qn))
True
"""

from __future__ import annotations

from typing import Dict, List, Set

from ..models import Questionnaire
from .report_generator import Finding

#: Choice-list size beyond which selection needs a search-style appearance.
_LONG_LIST = 50
#: Appearances that keep long lists usable on-device.
_SEARCH_APPEARANCES = ("autocomplete", "search", "minimal", "quick")
#: Form size (questions) beyond which load time is worth a heads-up.
_LARGE_FORM = 300


class ReadinessValidator:
    """Field-deployment readiness checks (deterministic)."""

    def validate(self, questionnaire: Questionnaire) -> List[Finding]:
        findings: List[Finding] = []
        findings.extend(self._translations(questionnaire))
        findings.extend(self._media(questionnaire))
        findings.extend(self._device(questionnaire))
        findings.extend(self._metadata(questionnaire))
        return findings

    # ------------------------------------------------------------------
    def _translatables(self, qn: Questionnaire):
        """(description, extra-dict, has_label) for every translatable item."""
        items = []
        for q in qn.questions:
            if q.is_structural or q.is_calculate:
                continue
            items.append((f"question '{q.name}'", q.extra,
                          bool(q.label or q.raw_label)))
        for list_name, cl in qn.choice_lists.items():
            for c in cl.choices:
                items.append((f"choice '{c.name}' in list '{list_name}'",
                              c.extra, bool(c.label)))
        return items

    def _translations(self, qn: Questionnaire) -> List[Finding]:
        items = self._translatables(qn)
        columns: Set[str] = set()
        for _, extra, _ in items:
            columns.update(k for k in extra
                           if k.startswith(("label::", "hint::")))
        findings: List[Finding] = []
        for column in sorted(columns):
            if column.startswith("hint::"):
                continue     # hints are optional per item; labels are not
            missing = [desc for desc, extra, has_label in items
                       if has_label and column not in extra]
            if missing:
                shown = ", ".join(missing[:5])
                more = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
                findings.append(Finding(
                    "warning", "readiness",
                    f"Translation '{column}' is incomplete: "
                    f"{len(missing)} item(s) still untranslated - enumerators "
                    f"would see mixed languages. Missing: {shown}{more}."))
        if columns and not qn.settings.default_language:
            findings.append(Finding(
                "warning", "readiness",
                "The form has translation columns but no default_language "
                "setting - platforms will guess which language to open with."))
        return findings

    # ------------------------------------------------------------------
    def _media(self, qn: Questionnaire) -> List[Finding]:
        files: Dict[str, str] = {}       # file -> first referencing question
        findings: List[Finding] = []
        for q in qn.questions:
            for key, value in q.extra.items():
                if not key.startswith("media::"):
                    continue
                if not (value or "").strip():
                    findings.append(Finding(
                        "warning", "readiness",
                        f"Question '{q.name}' has an empty {key} column - "
                        f"either name the file or remove the column.", q.name))
                else:
                    files.setdefault(value.strip(), q.name)
        if files:
            listing = ", ".join(sorted(files)[:8])
            more = f" (+{len(files) - 8} more)" if len(files) > 8 else ""
            findings.append(Finding(
                "info", "readiness",
                f"This form references {len(files)} media file(s) that must "
                f"be uploaded alongside it: {listing}{more}."))
        return findings

    # ------------------------------------------------------------------
    def _device(self, qn: Questionnaire) -> List[Finding]:
        findings: List[Finding] = []
        for q in qn.questions:
            if not q.references_choices:
                continue
            parts = (q.xlsform_type or "").split()
            list_name = parts[1] if len(parts) >= 2 else q.list_name
            cl = qn.choice_lists.get(list_name)
            if not cl or len(cl.choices) <= _LONG_LIST:
                continue
            appearance = (q.appearance or "").lower()
            if not any(a in appearance for a in _SEARCH_APPEARANCES):
                findings.append(Finding(
                    "warning", "readiness",
                    f"Question '{q.name}' offers {len(cl.choices)} options "
                    f"with no search-style appearance - scrolling that list "
                    f"is slow and error-prone on device. Consider "
                    f"appearance 'autocomplete' or 'minimal'.", q.name))
        real = [q for q in qn.questions if not q.is_structural]
        if len(real) > _LARGE_FORM:
            findings.append(Finding(
                "info", "readiness",
                f"The form has {len(real)} questions - expect slow load "
                f"times on low-end devices; consider splitting it."))
        return findings

    # ------------------------------------------------------------------
    def _metadata(self, qn: Questionnaire) -> List[Finding]:
        findings: List[Finding] = []
        if not qn.settings.version:
            findings.append(Finding(
                "info", "readiness",
                "No version is set - the tool generates one, but an "
                "explicit version makes round-to-round form management "
                "traceable."))
        return findings
