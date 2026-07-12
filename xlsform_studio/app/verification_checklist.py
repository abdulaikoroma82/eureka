"""Assumptions verification checklist (prioritized review of the log).

Purpose
-------
The assumption log records *every* decision the pipeline made, flat and in
order - which makes it complete but easy to ignore. Decisions that can make
a deployed form silently wrong (a compiled skip condition, an applied
constraint bound, an AI change a human accepted) sit next to routine
bookkeeping ("type inferred from keyword match"). This module restructures
the same entries into ``assumptions_to_verify.md``: a checklist sorted into
three tiers, each item with a checkbox and a concrete "what to verify"
action, so a reviewer can clear the critical items before deployment
without reading the whole log.

Tiers
-----
* **Critical - must verify before deployment**: logic resolutions,
  constraint applications, ambiguous type classifications, and every
  AI-applied change.
* **Advisory - recommended review**: AI translations, AI suggestions not
  applied, choice-list merges/sharing, auto-added specify follow-ups.
* **Informational - no action needed**: unambiguous keyword-match
  classifications and routine bookkeeping.

Every assumption is classified into exactly one tier by first-match against
an ordered pattern table; entries no rule recognises land in **Advisory**
(a decision we can't identify is safer reviewed than buried under "no
action needed"). This file supplements ``assumption_log.md``, never
replaces it - the log remains the complete, ordered record.

Inputs / outputs
----------------
The compiled :class:`~xlsform_studio.models.Questionnaire` and the same
``notes`` list the assumption log receives; returns/writes Markdown.

Example
-------
>>> md = VerificationChecklistBuilder().build_markdown(
...     Questionnaire(), ["[age] Default 'integer' constraint applied."])
>>> "Critical" in md and "- [ ]" in md
True
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Union

from ..models import Questionnaire

CRITICAL = "critical"
ADVISORY = "advisory"
INFO = "info"

#: Ordered classification table: the FIRST regex (case-insensitive, searched
#: anywhere in the message) that matches decides the tier and the action
#: text. ``{subject}`` in the action is replaced with the entry's variable /
#: module tag. Order matters: put the most specific patterns first.
_RULES: List[Tuple[str, str, str]] = [
    # --- Critical: AI-applied changes -----------------------------------
    (r"AI-suggested cross-field constraint",
     CRITICAL,
     "Verify the combined constraint is correct - the original and the AI "
     "addition are quoted in the assumption. Test with values that should "
     "pass and values that should fail."),
    (r"AI-suggested domain constraint",
     CRITICAL,
     "Confirm these bounds are appropriate for your population; the AI "
     "grounded them in the survey context, not your actual data."),
    (r"AI-suggested relevant condition",
     CRITICAL,
     "Verify the skip condition on '{subject}' shows/hides the question "
     "exactly when intended - walk through each answer that triggers it."),
    (r"AI reclassified",
     CRITICAL,
     "Confirm the reclassified type is right for '{subject}' - the "
     "original type was the deterministic engine's reading."),
    (r"AI-suggested rewording accepted",
     CRITICAL,
     "Confirm the new wording still asks exactly what the study needs - "
     "the original wording is quoted in the assumption."),
    (r"AI-suggested variable name accepted",
     CRITICAL,
     "Confirm the rename is reflected in your analysis scripts and data "
     "dictionary; all in-form references were updated automatically."),
    (r"AI-suggested (section grouping|choice-list reordering|enumerator "
     r"instruction) accepted",
     CRITICAL,
     "Review the applied change on '{subject}' in the exported XLSForm."),
    (r"\[AI suggestions\] Applied accepted",
     CRITICAL,
     "Review this applied AI change in the exported XLSForm."),
    # --- Critical: logic resolutions ------------------------------------
    (r"could not be auto-compiled",
     CRITICAL,
     "The skip instruction on '{subject}' was NOT compiled - add the "
     "relevant condition manually or the question will always show."),
    (r"Skip pattern detected",
     CRITICAL,
     "A 'skip to' instruction was interpreted; confirm the questions that "
     "should be skipped carry the right relevant condition."),
    (r"Relevant compiled from logic",
     CRITICAL,
     "Verify the compiled condition on '{subject}' matches the source "
     "instruction - test each answer that should show or hide it."),
    # --- Critical: constraint applications ------------------------------
    (r"Constraint applied from template match",
     CRITICAL,
     "Confirm these bounds are appropriate for your population - the "
     "template matched on keywords, not on your study design."),
    (r"Default '.*' constraint applied",
     CRITICAL,
     "Confirm the default bounds on '{subject}' are appropriate for your "
     "population."),
    # --- Critical: ambiguous type classifications -----------------------
    (r"No rule matched; defaulted to 'text'",
     CRITICAL,
     "No type rule matched '{subject}' - confirm free text is right, or "
     "correct the type in the source document."),
    (r"Wording implies multiple answers",
     CRITICAL,
     "Confirm '{subject}' should accept multiple answers "
     "(select_multiple), not a single choice."),
    (r"no answer options were found; add a choice list",
     CRITICAL,
     "'{subject}' is a select question with no options - add its choice "
     "list before deployment."),
    # --- Advisory --------------------------------------------------------
    (r"\[AI translation\]|translation cache",
     ADVISORY,
     "Have a native speaker review the AI translations before fieldwork."),
    (r"\[AI (naming|rewording|choice ordering|logic|classification|"
     r"cross-field constraints|domain constraints|enumerator notes|"
     r"coverage|indicators)\]",
     ADVISORY,
     "An AI suggestion or note that was NOT applied to the form - read it "
     "and decide whether to act on it manually."),
    (r"\[AI\]",
     ADVISORY,
     "Read this AI pipeline note; it explains something that was skipped "
     "or degraded."),
    (r"was identical to|Options identical to list",
     ADVISORY,
     "Two lists were merged/shared - confirm the questions genuinely use "
     "the same answer scale."),
    (r"'Other' option detected",
     ADVISORY,
     "A specify follow-up was auto-added - confirm its wording and "
     "placement suit the questionnaire."),
    (r"missing label\(s\)",
     ADVISORY,
     "A choice was kept despite a missing label - supply the label."),
    # --- Informational ---------------------------------------------------
    (r"inferred from keyword match",
     INFO, ""),
    (r"Yes/No options detected",
     INFO, ""),
    (r"derived from",
     INFO, ""),      # standard derived calculations (age from DOB, ...)
]

_COMPILED = [(re.compile(pat, re.IGNORECASE), tier, action)
             for pat, tier, action in _RULES]

_TIER_HEADERS = {
    CRITICAL: "## 🔴 Critical — Must Verify Before Deployment",
    ADVISORY: "## 🟠 Advisory — Recommended Review",
    INFO: "## 🔵 Informational — No Action Needed",
}


@dataclass
class ChecklistItem:
    """One classified assumption-log entry."""

    tier: str        # CRITICAL | ADVISORY | INFO
    subject: str     # variable name or module tag ("age", "AI translation")
    assumption: str  # the original log message
    action: str      # concrete "what to verify" text ("" for INFO)


class VerificationChecklistBuilder:
    """Turn the flat assumption log into a prioritized review checklist."""

    # ------------------------------------------------------------------
    def classify(self, note: str) -> ChecklistItem:
        """Classify one assumption-log entry into exactly one tier.

        Entries no rule recognises land in ADVISORY: an unidentified
        decision is safer flagged for review than filed under "no action
        needed".
        """
        subject, message = self._split(note)
        for pattern, tier, action in _COMPILED:
            if pattern.search(note):
                return ChecklistItem(
                    tier=tier, subject=subject, assumption=message,
                    action=action.replace("{subject}", subject))
        return ChecklistItem(
            tier=ADVISORY, subject=subject, assumption=message,
            action="Unrecognised decision type - read the assumption and "
                   "confirm it matches your intent.")

    # ------------------------------------------------------------------
    def build_markdown(self, questionnaire: Questionnaire,
                       notes: List[str], intro: str = "") -> str:
        """Build the checklist markdown.

        *intro* is optional AI-written framing prose (the "documents"
        feature); it is labelled and placed above the deterministic tallies
        and tiers, which it never alters.
        """
        items = [self.classify(n) for n in notes]
        by_tier = {tier: [i for i in items if i.tier == tier]
                   for tier in (CRITICAL, ADVISORY, INFO)}

        lines = ["# XLSForm Studio - Assumptions to Verify", ""]
        lines.append(f"**Form:** {questionnaire.settings.form_title}  ")
        lines.append(f"**Generated:** {_dt.datetime.now():%Y-%m-%d %H:%M}  ")
        if intro.strip():
            lines.append("")
            lines.append(f"> **AI-written.** {intro.strip()}")
        lines.append("")
        lines.append(f"**{len(by_tier[CRITICAL])} critical** · "
                     f"**{len(by_tier[ADVISORY])} advisory** · "
                     f"**{len(by_tier[INFO])} informational** "
                     f"({len(items)} decisions total)")
        lines.append("")
        lines.append("This checklist reorganises `assumption_log.md` by review "
                     "priority; the log itself remains the complete, ordered "
                     "record. Work through the critical items before "
                     "deployment - each one is a decision the tool made that "
                     "can make the form silently wrong if it guessed badly.")

        for tier in (CRITICAL, ADVISORY, INFO):
            lines.append("")
            lines.append(_TIER_HEADERS[tier])
            lines.append("")
            tier_items = by_tier[tier]
            if not tier_items:
                lines.append("_Nothing in this tier._")
                continue
            for item in tier_items:
                lines.append(f"- [ ] **`{item.subject}`** — {item.assumption}")
                if item.action:
                    lines.append(f"      **Verify:** {item.action}")
        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    def write(self, questionnaire: Questionnaire, notes: List[str],
              path: Union[str, Path], intro: str = "") -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.build_markdown(questionnaire, notes, intro),
                        encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    @staticmethod
    def _split(note: str) -> Tuple[str, str]:
        """Split ``[subject] message`` into its parts (same convention the
        assumption log uses)."""
        if note.startswith("["):
            subject, sep, message = note.partition("] ")
            if sep:
                return subject.lstrip("["), message
        return "form", note
