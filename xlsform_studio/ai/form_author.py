"""AI form authoring - the primary XLSForm compiler (AI-first pipeline).

Purpose
-------
This is the authoring heart of the AI-first pipeline. Given a raw
questionnaire (whatever the parser could extract: labels, free-text answer
options, natural-language skip instructions, sections) plus a target
platform, it asks the model to draft a *complete*, standards-compliant
XLSForm: for every item it fills in the field type, the machine name, the
respondent-facing label, hint, required flag, relevance (skip) logic,
constraints, calculations and choice lists - every column the survey and
choices sheets need.

Where this sits in the pipeline
-------------------------------
The deterministic layer brackets the AI on both sides:

    parse (deterministic scaffold)
      -> AIFormAuthor.author  (THIS module - AI fills the scaffold)
      -> deterministic standards enforcement (unique/valid names, choice
         normalisation) + validation

The AI decides *content*; the deterministic rules own the *contract* (which
columns/sheets exist, in which platform dialect) and *verify* the result.
The model can only write into fields this module recognises - it cannot
invent columns or sheets - which is how "rules keep the AI on-standard".

Before authoring, this module *reads* the deterministic naming rule
(``naming.max_length`` in the knowledge base) and states it in the prompt, so
the model is told the exact identifier limit up front; the same limit caps
the names this module accepts. AI and rules therefore agree by construction
rather than the rules having to reject and re-request oversized names.

Essential, not optional
-----------------------
Unlike the older enrichment modules, this one is required: a run cannot
produce a form without it. It therefore raises :class:`AIError` (never
silently degrades) when the client is unavailable or the response is
unusable, so the workflow can surface a clear failure to the user.

Inputs
------
A raw :class:`~xlsform_studio.models.Questionnaire`, an optional target
platform name (for dialect/standards context) and optional free-text survey
context.

Outputs
-------
The questionnaire, mutated in place with every resolved XLSForm field and
its choice lists, plus a list of human-readable notes describing what the
model produced and anything this module had to correct.

Example
-------
>>> AIFormAuthor(client=None).author(Questionnaire())   # doctest: +SKIP
[]
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from ..engine.knowledge_base import KnowledgeBase
from ..models import (Choice, ChoiceList, DECISION_CONFIDENCE_LEVELS,
                      Questionnaire, Question)
from .client import AIError, DeepSeekClient, MAX_QUESTIONS_FOR_AI
from .prompt_safety import INJECTION_GUARD, frame_untrusted

#: Fallback identifier length if the knowledge base names none. The
#: authoritative value is the deterministic ``naming.max_length`` rule in
#: ``knowledge/xlsform_rules.yaml``, which the author reads at construction.
_DEFAULT_MAX_NAME_LENGTH = 32

# The exact survey-sheet columns the model must populate, mirroring
# app.config.SURVEY_COLUMNS. Kept as a literal here so the prompt states the
# contract verbatim rather than importing the UI config into the AI layer.
_SURVEY_FIELDS = (
    "type", "name", "label", "hint", "required", "relevant",
    "constraint", "constraint_message", "calculation",
    "choice_filter", "appearance", "default",
)

# Valid XLSForm base types the author may emit. select_one / select_multiple
# / rank take a second token naming a choice list defined in "choices".
_ALLOWED_BASE_TYPES = (
    "select_one", "select_multiple", "rank",
    "integer", "decimal", "text", "date", "time", "datetime",
    "geopoint", "geotrace", "geoshape",
    "image", "audio", "video", "barcode",
    "calculate", "note", "range", "acknowledge",
)

_NAME_RE = re.compile(r"[^a-z0-9_]")

_SYSTEM_PROMPT = (
    "You are an expert XLSForm engineer. You convert raw questionnaire items "
    "into a complete, standards-compliant XLSForm ready for deployment on "
    "{platform}. For EVERY input item you produce one fully-specified survey "
    "row, and for every choice question you also define the choice list it "
    "references.\n\n"
    "Survey row fields you must set: " + ", ".join(_SURVEY_FIELDS) + ".\n\n"
    "Read these deterministic standards FIRST. A rule engine re-checks every "
    "row after you author it and rejects anything that breaks them (sending "
    "it back for slow human review), so comply exactly up front:\n"
    "- type: one valid XLSForm type. For choice questions use "
    "'select_one <list>' or 'select_multiple <list>', where <list> is a "
    "lowercase snake_case name you also define under \"choices\". Other "
    "allowed base types: integer, decimal, text, date, time, datetime, "
    "geopoint, geotrace, geoshape, image, audio, video, barcode, calculate, "
    "note, range, acknowledge.\n"
    "- name: a UNIQUE, lowercase snake_case identifier (a-z, 0-9, underscore; "
    "must start with a letter) of AT MOST {max_name} characters. Derive it "
    "from the item's meaning; keep it concise. Never reuse a name.\n"
    "- label: the respondent-facing wording, cleaned up for clarity and "
    "consistency. Preserve the original meaning and language.\n"
    "- hint: a short clarifying instruction for the enumerator, or \"\".\n"
    "- required: true only when the item must be answered.\n"
    "- relevant: an ODK/XLSForm XPath skip/display expression referencing "
    "OTHER answers as ${{name}} (only names you define), using =, !=, >, <, "
    ">=, <=, and, or, not(), selected(${{q}},'code'). Use \"\" when the item "
    "is always shown. Base it on the item's natural-language logic when given.\n"
    "- constraint: an XPath validation on '.' (the current answer), e.g. "
    "'. >= 0 and . <= 120'; with a friendly constraint_message. Use \"\" when "
    "no constraint applies.\n"
    "- calculation: only for type 'calculate'; otherwise \"\".\n"
    "- choice_filter, appearance, default: set only when genuinely needed, "
    "else \"\".\n"
    "- confidence: your confidence for this row - one of high, medium, low.\n"
    "- reason: one short clause on any non-obvious choice (type, logic, "
    "constraint). Keep it brief.\n\n"
    "Every input index MUST appear exactly once in \"questions\". Every "
    "select/rank list named in a type MUST be defined in \"choices\". Respond "
    "with ONLY a json object of the form: "
    "{{\"questions\": [{{\"index\": 0, \"type\": \"...\", \"name\": \"...\", "
    "\"label\": \"...\", \"hint\": \"\", \"required\": false, \"relevant\": "
    "\"\", \"constraint\": \"\", \"constraint_message\": \"\", "
    "\"calculation\": \"\", \"choice_filter\": \"\", \"appearance\": \"\", "
    "\"default\": \"\", \"confidence\": \"high\", \"reason\": \"\"}}], "
    "\"choices\": {{\"list_name\": [{{\"name\": \"code\", \"label\": "
    "\"Label\"}}]}}}}."
)


class AIFormAuthor:
    """Draft a complete XLSForm from a raw questionnaire via the model.

    The single public method :meth:`author` mutates the questionnaire in
    place and returns notes. It raises :class:`AIError` when the model is
    unavailable or its response cannot be used at all - authoring is
    essential, so failing loudly is correct.
    """

    def __init__(self, client: Optional[DeepSeekClient],
                 knowledge: Optional[KnowledgeBase] = None) -> None:
        self.client = client
        # Read the deterministic naming rule the standards layer enforces, so
        # the model is told the exact identifier length up front and this
        # module caps names to the same limit - AI and rules agree by design.
        kb = knowledge or KnowledgeBase.load()
        self._max_name_length = int(
            kb.naming_rules().get("max_length", _DEFAULT_MAX_NAME_LENGTH))

    # ------------------------------------------------------------------
    def author(self, questionnaire: Questionnaire, *,
               target: Optional[str] = None,
               survey_context: str = "") -> List[str]:
        items = [q for q in questionnaire.questions if (q.raw_label or "").strip()]
        if not items:
            return []

        if self.client is None or not self.client.available:
            raise AIError(
                "AI authoring is required but no DeepSeek API key is "
                "configured. Set the DEEPSEEK_API_KEY environment variable.")

        if len(items) > MAX_QUESTIONS_FOR_AI:
            raise AIError(
                f"Questionnaire has {len(items)} items, above the "
                f"{MAX_QUESTIONS_FOR_AI}-item limit for a single AI request.")

        response = self._request(items, target, survey_context)
        return self._apply(questionnaire, items, response)

    # ------------------------------------------------------------------
    def _request(self, items: List[Question], target: Optional[str],
                 survey_context: str) -> dict:
        platform = (target or "a generic ODK-compatible platform").strip() \
            or "a generic ODK-compatible platform"
        system_prompt = _SYSTEM_PROMPT.format(
            platform=platform, max_name=self._max_name_length) + INJECTION_GUARD

        payload = []
        for idx, q in enumerate(items):
            entry: Dict[str, object] = {"index": idx, "text": q.raw_label}
            if q.raw_choices:
                entry["answer_options"] = q.raw_choices
            if (q.logic or "").strip():
                entry["skip_logic_hint"] = q.logic
            if (q.section or "").strip():
                entry["section"] = q.section
            if (q.instruction or "").strip():
                entry["instruction"] = q.instruction
            if (q.source_number or "").strip():
                entry["source_number"] = q.source_number
            payload.append(entry)

        user_prompt = ""
        context = frame_untrusted("Survey context", survey_context)
        if context:
            user_prompt += context + "\n"
        user_prompt += ("Questionnaire items to convert (json):\n"
                        + json.dumps(payload, ensure_ascii=False))

        # Budget scales with the form: each row is a small object plus its
        # choices. Generous ceiling, capped by the API's own limits.
        max_tokens = min(8000, max(1500, len(items) * 220))
        return self.client.complete_json(system_prompt, user_prompt,
                                         max_tokens=max_tokens)

    # ------------------------------------------------------------------
    def _apply(self, qn: Questionnaire, items: List[Question],
               response: dict) -> List[str]:
        notes: List[str] = []

        rows = response.get("questions")
        if not isinstance(rows, list):
            raise AIError("AI author response had no 'questions' list.")

        by_index: Dict[int, dict] = {}
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("index"), int):
                by_index[row["index"]] = row

        # First pass: assign fields, tracking name uniqueness.
        used_names: set = set()
        referenced_lists: set = set()
        for idx, q in enumerate(items):
            row = by_index.get(idx)
            if row is None:
                notes.append(f"[AI author] No row returned for item "
                            f"{idx + 1} ({_short(q.raw_label)}); left blank "
                            f"for review.")
                continue
            self._assign_row(q, row, used_names, referenced_lists, notes)

        # Build choice lists the rows referenced.
        self._build_choices(qn, response.get("choices"), referenced_lists, notes)

        notes.insert(0, f"[AI author] Drafted {len(by_index)} of "
                        f"{len(items)} item(s) into a complete XLSForm; "
                        f"every field is AI-authored and awaiting your review.")
        return notes

    # ------------------------------------------------------------------
    def _assign_row(self, q: Question, row: dict, used_names: set,
                    referenced_lists: set, notes: List[str]) -> None:
        xls_type = str(row.get("type", "")).strip()
        base = xls_type.split(" ", 1)[0] if xls_type else ""
        if base not in _ALLOWED_BASE_TYPES:
            notes.append(f"[AI author] Unrecognised type "
                        f"'{xls_type}' for {_short(q.raw_label)}; defaulted "
                        f"to text for review.")
            xls_type, base = "text", "text"

        q.xlsform_type = xls_type
        q.name = self._unique_name(row.get("name", ""), q.raw_label, used_names)
        q.label = str(row.get("label") or q.raw_label).strip()
        q.hint = str(row.get("hint") or "").strip()
        q.required = bool(row.get("required", False))
        q.relevant = str(row.get("relevant") or "").strip()
        q.constraint = str(row.get("constraint") or "").strip()
        q.constraint_message = str(row.get("constraint_message") or "").strip()
        q.calculation = str(row.get("calculation") or "").strip()
        q.choice_filter = str(row.get("choice_filter") or "").strip()
        q.appearance = str(row.get("appearance") or "").strip()
        q.default = str(row.get("default") or "").strip()

        # For choice types, capture the referenced list so we can build it.
        if base in ("select_one", "select_multiple", "rank"):
            parts = xls_type.split()
            list_name = parts[1] if len(parts) >= 2 else ""
            if list_name and list_name != "or_other":
                q.list_name = list_name
                referenced_lists.add(list_name)

        conf = str(row.get("confidence", "medium"))
        if conf not in DECISION_CONFIDENCE_LEVELS:
            conf = "medium"
        reason = str(row.get("reason") or "").strip() or \
            "AI-authored from the source item."
        q.add_decision("type", xls_type, conf,
                       f"AI authored type '{xls_type}'. {reason}")
        if q.relevant:
            q.add_decision("relevant", q.relevant, conf,
                          "AI authored skip/display logic. Please review.")
        if q.constraint:
            q.add_decision("constraint", q.constraint, conf,
                          "AI authored constraint. Please review.")

    # ------------------------------------------------------------------
    def _build_choices(self, qn: Questionnaire, choices: object,
                       referenced_lists: set, notes: List[str]) -> None:
        if not isinstance(choices, dict):
            if referenced_lists:
                notes.append("[AI author] Response defined no choice lists "
                            "despite select questions; those lists are empty "
                            "and need review.")
            return

        for list_name, options in choices.items():
            if not isinstance(options, list):
                continue
            built: List[Choice] = []
            seen_codes: set = set()
            for opt in options:
                if isinstance(opt, dict):
                    code = str(opt.get("name") or "").strip()
                    label = str(opt.get("label") or opt.get("name") or "").strip()
                elif isinstance(opt, str):
                    code, label = "", opt.strip()
                else:
                    continue
                if not label:
                    continue
                code = self._unique_name(code, label, seen_codes)
                built.append(Choice(name=code, label=label))
            if built:
                qn.choice_lists[str(list_name)] = ChoiceList(
                    list_name=str(list_name), choices=built)

        missing = referenced_lists - set(qn.choice_lists)
        if missing:
            notes.append(f"[AI author] {len(missing)} referenced choice "
                        f"list(s) were not defined ({', '.join(sorted(missing))}); "
                        f"they are empty and need review.")

    # ------------------------------------------------------------------
    def _unique_name(self, proposed: str, fallback_label: str,
                     used: set) -> str:
        """Sanitise *proposed* to a valid XLSForm identifier, deriving one
        from *fallback_label* if blank, then guarantee uniqueness within
        *used* (which this method updates)."""
        name = self._sanitize(proposed) or self._sanitize(fallback_label) or "q"
        if name not in used:
            used.add(name)
            return name
        # Append a uniqueness suffix WITHIN the length limit - trim the base so
        # base+suffix still fits, or a collision on a max-length name would
        # overflow the platform's identifier limit (e.g. SurveyCTO's 32).
        n = 2
        limit = self._max_name_length
        while True:
            suffix = f"_{n}"
            candidate = f"{name[:max(1, limit - len(suffix))]}{suffix}"
            if candidate not in used:
                used.add(candidate)
                return candidate
            n += 1

    def _sanitize(self, text: str) -> str:
        s = _NAME_RE.sub("_", str(text).strip().lower())
        s = re.sub(r"_+", "_", s).strip("_")
        if s and s[0].isdigit():
            s = "q_" + s
        return s[:self._max_name_length]


def _short(text: str, limit: int = 40) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[:limit - 1] + "…"
