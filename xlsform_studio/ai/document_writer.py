"""AI document co-writer (optional AI feature; "documents").

Purpose
-------
The supporting deliverables that ship beside the XLSForm - the enumerator
guide, the data-collection plan, the logic map, the printable survey
instrument, the assumptions-to-verify checklist - are *authored
deterministically* by :mod:`xlsform_studio.app.artifacts` and
:mod:`xlsform_studio.app.verification_checklist`. Those builders own every
fact: variable names, types, logic expressions, question counts, device
requirements, checklist tiers. This module lets the model **co-write** the
natural-language prose that frames those facts - a short orientation for the
enumerator guide, a readable overview for the collection plan, a plain-English
summary of the skip logic - so the documents read like a human wrote them
without the model ever touching a fact.

Division of authority (identical to :mod:`~xlsform_studio.ai.narrative`)
------------------------------------------------------------------------
Rules build the document and own every number, name and expression; AI writes
only the designated prose blocks, which the builders slot into fixed,
clearly-labelled positions. Turn AI off and every document is byte-for-byte
what it is today - the prose blocks are simply absent. The model is given
*derived facts only* (counts, section names, duration, device needs, finding
tallies), never asked to compute or restate them, and is told in the prompt to
introduce no fact or number of its own.

Design
------
One API call per form produces every prose block at once (bounds cost, per the
standing acceptance criteria). Each block is capped and sanitised; a block the
model leaves empty simply means that document renders without an intro. Fails
open: any error returns empty prose and a note, and the deterministic
documents stand unchanged.

Inputs
------
The compiled :class:`~xlsform_studio.models.Questionnaire`, the deterministic
:class:`~xlsform_studio.analysis.duration.DurationEstimate` and
:class:`~xlsform_studio.analysis.quality_score.QualityIndex`, and the
:class:`~xlsform_studio.validation.report_generator.ValidationReport`.

Outputs
-------
``(DocumentProse, notes)`` - the prose is an all-empty :class:`DocumentProse`
when the feature is off or the call fails.

Example
-------
>>> AIDocumentWriter(client=None)   # doctest: +SKIP
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..analysis.duration import DurationEstimate
from ..analysis.quality_score import QualityIndex
from ..models import Questionnaire
from ..validation.report_generator import ValidationReport
from .client import AIError, DeepSeekClient

#: Upper bound on each prose block, so a runaway response can't bloat a
#: document. Generous enough for a short paragraph, tight enough to stay a
#: framing intro rather than a re-authored document.
_MAX_PROSE_CHARS = 1200


@dataclass
class DocumentProse:
    """AI-written prose blocks, one per prose-bearing document.

    Every field defaults to ``""`` - the deterministic builders render a
    document exactly as before when its block is empty, so this object is
    always safe to pass and an all-empty instance is a no-op.
    """

    #: Orientation paragraph opening the enumerator reference guide.
    enumerator_intro: str = ""
    #: Overview narrative for the data-collection plan.
    collection_plan_overview: str = ""
    #: Plain-English summary of the form's skip/constraint/calculation logic.
    logic_overview: str = ""
    #: Intro paragraph under the title of the printable survey instrument.
    instrument_intro: str = ""
    #: Framing intro for the assumptions-to-verify checklist.
    assumptions_intro: str = ""

    @property
    def any(self) -> bool:
        """True if the model produced at least one non-empty block."""
        return any((self.enumerator_intro, self.collection_plan_overview,
                    self.logic_overview, self.instrument_intro,
                    self.assumptions_intro))


#: The prose blocks the model must return, and what each frames. Kept as data
#: so the prompt and the parser stay in lockstep.
_BLOCKS = {
    "enumerator_intro":
        "a 2-3 sentence orientation opening the ENUMERATOR REFERENCE GUIDE: "
        "how to use it in the field, that the device enforces skip logic "
        "automatically, and the professional tone to keep with respondents.",
    "collection_plan_overview":
        "a 2-4 sentence overview for the DATA-COLLECTION PLAN: what this "
        "instrument collects and its shape, referencing only the provided "
        "counts/sections/duration; do not invent sampling or logistics.",
    "logic_overview":
        "a 2-4 sentence plain-English summary of the form's LOGIC (how skip "
        "rules, constraints and calculations shape the interview), based only "
        "on the provided counts; the authoritative expressions follow in a "
        "table you must not restate.",
    "instrument_intro":
        "a 1-2 sentence intro under the title of the PRINTABLE SURVEY "
        "INSTRUMENT, orienting a reader of the paper questionnaire.",
    "assumptions_intro":
        "a 2-3 sentence framing for the ASSUMPTIONS-TO-VERIFY checklist: why "
        "the automatic decisions below deserve a review pass before "
        "deployment, encouraging attention to the critical tier first.",
}

_SYSTEM_PROMPT = (
    "You are a survey documentation editor. Deterministic tooling has already "
    "authored a set of survey deliverables and owns every fact in them "
    "(variable names, types, logic expressions, counts, device needs, "
    "checklist tiers). Your ONLY job is to write short, polished, professional "
    "prose that frames those facts in each document - you never state a fact, "
    "number, name or expression that is not in the metrics given to you, and "
    "you never contradict them. If a document has nothing to add, return an "
    "empty string for it.\n\n"
    "You are given pre-computed metrics for one questionnaire. Write these "
    "blocks:\n"
    + "".join(f"- {k}: {v}\n" for k, v in _BLOCKS.items())
    + "\nEach block is plain prose (no markdown headings, no lists, no code). "
    "Respond with ONLY a json object mapping each block name to its string, "
    "e.g. {" + ", ".join(f"\"{k}\": \"...\"" for k in _BLOCKS) + "}."
)


class AIDocumentWriter:
    """Co-write the prose of the supporting documents via DeepSeek."""

    def __init__(self, client: Optional[DeepSeekClient]) -> None:
        self.client = client

    # ------------------------------------------------------------------
    def write(self, questionnaire: Questionnaire, *,
              duration: Optional[DurationEstimate] = None,
              quality: Optional[QualityIndex] = None,
              report: Optional[ValidationReport] = None
              ) -> Tuple[DocumentProse, List[str]]:
        """Produce the prose blocks. Fails open to empty prose + a note."""
        if self.client is None or not self.client.available:
            return DocumentProse(), []

        payload = self._facts(questionnaire, duration, quality, report)
        try:
            response = self.client.complete_json(
                _SYSTEM_PROMPT,
                "Metrics (json):\n" + json.dumps(payload, ensure_ascii=False),
                max_tokens=900)
        except AIError as exc:
            return DocumentProse(), [f"[AI documents] Skipped: {exc}"]

        prose = DocumentProse(**{
            key: self._clean(response.get(key, "")) for key in _BLOCKS})
        if not prose.any:
            return prose, ["[AI documents] The model returned no usable prose; "
                           "the deterministic documents stand."]
        return prose, ["[AI documents] Co-wrote the framing prose of the "
                       "supporting documents (AI-written; every fact remains "
                       "deterministic)."]

    # ------------------------------------------------------------------
    @staticmethod
    def _facts(qn: Questionnaire, duration: Optional[DurationEstimate],
               quality: Optional[QualityIndex],
               report: Optional[ValidationReport]) -> dict:
        real = [q for q in qn.questions
                if not q.is_structural and not q.is_calculate]
        sections = [s for s in dict.fromkeys(q.section for q in real) if s]
        types = {q.base_type for q in real}
        device = {
            "gps": "geopoint" in types,
            "camera": bool(types & {"image", "video", "barcode"}),
            "microphone": bool(types & {"audio", "video"}),
        }
        languages = sorted({k.split("::", 1)[1] for q in qn.questions
                            for k in q.extra if k.startswith("label::")})
        facts = {
            "form_title": qn.settings.form_title,
            "question_count": len(real),
            "section_names": sections,
            "counts": {
                "with_skip_logic": sum(1 for q in qn.questions if q.relevant),
                "with_constraints": sum(1 for q in qn.questions if q.constraint),
                "calculated_fields": sum(1 for q in qn.questions
                                         if q.is_calculate),
                "choice_questions": sum(1 for q in real if q.references_choices),
            },
            "device_needs": device,
            "extra_languages": languages,
        }
        if duration is not None:
            facts["duration"] = duration.to_dict()
        if quality is not None:
            facts["quality_index"] = quality.to_dict()
        if report is not None:
            facts["validation"] = {"errors": len(report.errors),
                                   "warnings": len(report.warnings),
                                   "is_valid": report.is_valid}
        return facts

    @staticmethod
    def _clean(value: object) -> str:
        text = " ".join(str(value or "").split())
        return text[:_MAX_PROSE_CHARS].strip()
