"""Choice-list semantic auditor (deterministic quality checks).

Purpose
-------
The structural validators catch broken choice lists (missing, duplicated,
unlabelled). This auditor catches *semantically flawed but structurally
valid* lists - the kind that deploy without a single error and then
quietly degrade the data: a Likert scale missing its midpoint, options in
scrambled order, an "Other" with no specify field to catch the answers,
value coding that will confuse the analyst.

Checks (all deterministic - no AI, no network)
----------------------------------------------
1. **Ordinal scale gaps** - recognises Likert/frequency/satisfaction/
   agreement/quality scales by label and flags missing intermediate
   categories ("Very good, Good, Poor, Very poor" -> missing "Fair").
2. **Ordering violations** - lists with a logical order (days, months,
   size categories, primary/secondary/tertiary, recognised ordinal
   scales, numeric-prefixed ranges, integer codes) listed out of order.
3. **"Other, specify"** - an "Other" option must have a follow-up text
   question whose relevant references the parent and the other value
   (error if missing); ``or_other`` without an explicit Other option in
   the list is a warning (platforms may auto-add one).
4. **Value-label mismatch** - non-sequential integer codes (1, 3, 5)
   under categorical labels, with no obvious encoding scheme (Yes/No
   with 0/1 or 1/0 is fine and never flagged).
5. **Unbalanced value ranges** - tightly clustered codes with distant
   outliers (1, 2, 3, 99): flagged so the user confirms the sentinel /
   missing-value coding is intentional.

Severity: a missing specify field is an **error** (answer data will be
lost); everything else is a **warning**.

Inputs / outputs
----------------
A compiled :class:`~xlsform_studio.models.Questionnaire`; returns
:class:`~xlsform_studio.validation.report_generator.Finding` objects in
category ``choice_quality``.

Example
-------
>>> from xlsform_studio.models import (Questionnaire, Question, Choice,
...                                    ChoiceList)
>>> qn = Questionnaire(
...     questions=[Question(name="q", label="Q?",
...                         xlsform_type="select_one days",
...                         list_name="days")],
...     choice_lists={"days": ChoiceList("days", [
...         Choice("wed", "Wednesday"), Choice("mon", "Monday"),
...         Choice("tue", "Tuesday")])})
>>> any("logical order" in f.message for f in ChoiceAuditor().validate(qn))
True
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence

from ..models import ChoiceList, Question, Questionnaire
from .report_generator import Finding

# --- Check 1: known ordinal scales, in canonical order ----------------------
#: Each scale is its full canonical term sequence (normalized lowercase).
#: A list matching >= 3 terms of one scale with a positional gap is flagged.
_ORDINAL_SCALES: Dict[str, Sequence[str]] = {
    "quality rating": ("very good", "good", "fair", "poor", "very poor"),
    "agreement (Likert)": ("strongly agree", "agree",
                           "neither agree nor disagree", "disagree",
                           "strongly disagree"),
    "satisfaction": ("very satisfied", "satisfied",
                     "neither satisfied nor dissatisfied", "dissatisfied",
                     "very dissatisfied"),
    "frequency": ("always", "often", "sometimes", "rarely", "never"),
    "likelihood": ("very likely", "likely",
                   "neither likely nor unlikely", "unlikely",
                   "very unlikely"),
    "importance": ("very important", "important", "moderately important",
                   "slightly important", "not important"),
}

#: Alternative wordings accepted for a canonical scale term (midpoints vary).
_TERM_SYNONYMS: Dict[str, str] = {
    "neutral": "neither agree nor disagree",
    "neither": "neither agree nor disagree",
    "agree nor disagree": "neither agree nor disagree",
    "average": "fair",
    "ok": "fair",
    "okay": "fair",
    "moderate": "moderately important",
}

# --- Check 2: known ordered sequences ---------------------------------------
_DAY_ORDER = ("monday", "tuesday", "wednesday", "thursday", "friday",
              "saturday", "sunday")
_MONTH_ORDER = ("january", "february", "march", "april", "may", "june",
                "july", "august", "september", "october", "november",
                "december")
_SIZE_ORDER = ("extra small", "small", "medium", "large", "extra large")
_LEVEL_ORDER = ("primary", "secondary", "tertiary")

_ORDERED_SEQUENCES: Dict[str, Sequence[str]] = {
    "days of the week": _DAY_ORDER,
    "months": _MONTH_ORDER,
    "size categories": _SIZE_ORDER,
    "education/level sequence": _LEVEL_ORDER,
    **{f"the {name} scale": terms for name, terms in _ORDINAL_SCALES.items()},
}

_LEADING_NUMBER = re.compile(r"^\s*(\d+(?:\.\d+)?)")

#: Codes conventionally used for "don't know / refused / missing".
_SENTINEL_CODES = {77, 88, 96, 97, 98, 99, 777, 888, 996, 997, 998, 999,
                   -77, -88, -99}


class ChoiceAuditor:
    """Run the five deterministic choice-list quality checks."""

    # ------------------------------------------------------------------
    def validate(self, questionnaire: Questionnaire) -> List[Finding]:
        findings: List[Finding] = []
        for name, cl in questionnaire.choice_lists.items():
            if len(cl.choices) < 2:
                continue
            findings.extend(self._check_scale_gaps(name, cl))
            findings.extend(self._check_ordering(name, cl))
            findings.extend(self._check_value_label_mismatch(name, cl))
            findings.extend(self._check_unbalanced_values(name, cl))
        findings.extend(self._check_other_specify(questionnaire))
        return findings

    # ------------------------------------------------------------------
    # Check 1: ordinal scale gaps
    # ------------------------------------------------------------------
    def _check_scale_gaps(self, name: str, cl: ChoiceList) -> List[Finding]:
        labels = [self._norm(c.label) for c in cl.choices]
        findings: List[Finding] = []
        for scale_name, terms in _ORDINAL_SCALES.items():
            positions = sorted(terms.index(lab) for lab in set(labels)
                               if lab in terms)
            if len(positions) < 3:
                continue
            missing = [terms[i]
                       for i in range(positions[0], positions[-1] + 1)
                       if i not in positions]
            if missing:
                findings.append(Finding(
                    "warning", "choice_quality",
                    f"Choice list '{name}' looks like a {scale_name} scale "
                    f"but skips intermediate categor"
                    f"{'y' if len(missing) == 1 else 'ies'}: "
                    f"{', '.join(m.title() for m in missing)}. An "
                    f"unbalanced scale biases responses toward the "
                    f"remaining options.", name))
            break   # a list matches at most one scale meaningfully
        return findings

    # ------------------------------------------------------------------
    # Check 2: ordering violations
    # ------------------------------------------------------------------
    def _check_ordering(self, name: str, cl: ChoiceList) -> List[Finding]:
        labels = [self._norm(c.label) for c in cl.choices]

        # Known label sequences (days, months, sizes, scales, levels).
        for seq_name, order in _ORDERED_SEQUENCES.items():
            matched = [lab for lab in labels if lab in order]
            if len(matched) < 3 or len(matched) != len(labels):
                continue
            indices = [order.index(lab) for lab in labels]
            if self._in_order(indices):
                continue
            # Days/months may legitimately rotate (week starting Sunday);
            # accept any rotation of the canonical order.
            if seq_name in ("days of the week", "months") \
                    and self._is_rotation(indices, len(order)):
                continue
            expected = sorted(labels, key=order.index)
            return [Finding(
                "warning", "choice_quality",
                f"Choice list '{name}' contains {seq_name} out of their "
                f"logical order: listed as "
                f"{', '.join(l.title() for l in labels)}; expected "
                f"{', '.join(l.title() for l in expected)}.", name)]

        # Numeric-prefixed labels ("1-5 years", "6-10 years") - checked on
        # the raw labels, since normalization strips the digits.
        numbers = [self._leading_number(c.label) for c in cl.choices]
        if all(n is not None for n in numbers) and len(set(numbers)) > 2:
            if not self._in_order(numbers):
                return [Finding(
                    "warning", "choice_quality",
                    f"Choice list '{name}' has numeric labels that are not "
                    f"in ascending order - respondents and analysts expect "
                    f"ranges to run low to high.", name)]
        return []

    # ------------------------------------------------------------------
    # Check 3: "Other, specify"
    # ------------------------------------------------------------------
    def _check_other_specify(self, qn: Questionnaire) -> List[Finding]:
        findings: List[Finding] = []
        questions = [q for q in qn.questions if not q.is_structural]
        for q in questions:
            if not q.references_choices or not q.name:
                continue
            or_other = "or_other" in (q.xlsform_type or "")
            cl = qn.choice_lists.get(self._list_name(q))
            other = self._other_choice(cl) if cl else None

            if or_other and other is None:
                findings.append(Finding(
                    "warning", "choice_quality",
                    f"'{q.name}' uses 'or_other' but its list has no "
                    f"explicit Other option - the platform may auto-add "
                    f"one, but the auto-added answer has no specify "
                    f"follow-up and the label cannot be translated. "
                    f"Prefer an explicit Other choice plus a text "
                    f"follow-up.", q.name))
                continue
            if other is None:
                continue

            if not self._has_specify_followup(q, other.name, questions):
                findings.append(Finding(
                    "error", "choice_quality",
                    f"'{q.name}' offers an Other option ('{other.label}') "
                    f"but no follow-up text question captures what "
                    f"\"other\" is - add a text question with relevant "
                    f"selected(${{{q.name}}}, '{other.name}') or the "
                    f"answers will be unrecoverable.", q.name))
        return findings

    @staticmethod
    def _other_choice(cl: Optional[ChoiceList]):
        if cl is None:
            return None
        for c in cl.choices:
            label = (c.label or "").strip().lower()
            if c.name == "other" or label == "other" \
                    or label.startswith("other ") or label.startswith("other,"):
                return c
        return None

    @staticmethod
    def _has_specify_followup(q: Question, other_value: str,
                              questions: List[Question]) -> bool:
        ref = f"${{{q.name}}}"
        for candidate in questions:
            if candidate is q or candidate.base_type != "text":
                continue
            rel = candidate.relevant or ""
            if ref in rel and (f"'{other_value}'" in rel
                               or f'"{other_value}"' in rel):
                return True
        return False

    # ------------------------------------------------------------------
    # Check 4: value-label mismatch
    # ------------------------------------------------------------------
    def _check_value_label_mismatch(self, name: str,
                                    cl: ChoiceList) -> List[Finding]:
        values = [self._as_int(c.name) for c in cl.choices]
        if any(v is None for v in values) or len(values) < 2:
            return []
        ordered = sorted(values)

        # Yes/No-style binary coding is conventional - never flag it.
        if set(values) in ({0, 1}, {1, 2}):
            return []
        # Sequential (possibly unordered - check 2 owns ordering).
        if all(b - a == 1 for a, b in zip(ordered, ordered[1:])):
            return []
        # Sentinel outliers are check 5's subject, not a coding mismatch.
        non_sentinel = [v for v in ordered if v not in _SENTINEL_CODES]
        if len(non_sentinel) != len(ordered):
            return []
        # Labels that contain their own code ("Grade 5") are an encoding.
        labels_encode = all(
            str(v) in (c.label or "")
            for v, c in zip(values, cl.choices))
        if labels_encode:
            return []
        return [Finding(
            "warning", "choice_quality",
            f"Choice list '{name}' uses non-sequential codes "
            f"({', '.join(str(v) for v in values)}) for categorical "
            f"labels with no obvious encoding scheme - valid, but "
            f"analysts often assume sequential coding; confirm this is "
            f"intentional.", name)]

    # ------------------------------------------------------------------
    # Check 5: unbalanced value ranges
    # ------------------------------------------------------------------
    def _check_unbalanced_values(self, name: str,
                                 cl: ChoiceList) -> List[Finding]:
        values = sorted(v for v in (self._as_int(c.name) for c in cl.choices)
                        if v is not None)
        if len(values) < 3:
            return []
        cluster, outliers = values[:-1], values[-1]
        span = cluster[-1] - cluster[0]
        # Outlier: the top code sits far beyond the rest of the cluster
        # (a 1,2,3,99 pattern), or uses a conventional sentinel code.
        distant = outliers - cluster[-1] > max(span, 1) * 3
        if distant or (outliers in _SENTINEL_CODES
                       and cluster[-1] < min(_SENTINEL_CODES,
                                             key=abs)):
            return [Finding(
                "warning", "choice_quality",
                f"Choice list '{name}' has codes {cluster} plus a distant "
                f"outlier {outliers} - if {outliers} is a "
                f"don't-know/refused code, confirm your analysis plan "
                f"treats it as missing rather than a value.", name)]
        return []

    # ------------------------------------------------------------------
    @staticmethod
    def _norm(label: str) -> str:
        text = re.sub(r"[^a-z ]", "", (label or "").lower()).strip()
        text = re.sub(r"\s+", " ", text)
        return _TERM_SYNONYMS.get(text, text)

    @staticmethod
    def _in_order(indices: Sequence) -> bool:
        return all(a <= b for a, b in zip(indices, indices[1:]))

    @staticmethod
    def _is_rotation(indices: Sequence[int], modulus: int) -> bool:
        """True when indices are consecutive modulo *modulus* (e.g. a week
        listed Sunday-first)."""
        return all((b - a) % modulus == 1
                   for a, b in zip(indices, indices[1:]))

    @staticmethod
    def _as_int(value: str) -> Optional[int]:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _leading_number(label: str) -> Optional[float]:
        m = _LEADING_NUMBER.match(label or "")
        return float(m.group(1)) if m else None

    @staticmethod
    def _list_name(q: Question) -> str:
        parts = (q.xlsform_type or "").split()
        return parts[1] if len(parts) >= 2 else q.list_name
