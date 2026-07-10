"""Core data models (the intermediate representation).

Purpose
-------
Define the deterministic, framework-agnostic data structures that flow
through the whole pipeline:

    parser  ->  Questionnaire  ->  engine  ->  Questionnaire (enriched)
            ->  xlsform builder ->  XLSForm rows  ->  exporter

Every module in the project speaks in terms of these objects, which keeps
the architecture modular: a parser only needs to produce a ``Questionnaire``
and the rest of the pipeline works unchanged.

Inputs / outputs
----------------
These are plain ``dataclass`` containers.  They carry no behaviour beyond
light serialisation helpers (``to_dict`` / ``from_dict``) used for the JSON
input format and the assumption/logic logs.

Example
-------
>>> q = Question(raw_label="Child age in months", name="child_age_months",
...              xlsform_type="integer", label="Child age in months")
>>> q.is_select
False
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------
#: Structural row types that open/close groups and repeats.
STRUCTURAL_TYPES = ("begin group", "end group", "begin repeat", "end repeat")


@dataclass
class Choice:
    """A single answer option within a choice list.

    Attributes
    ----------
    name:
        Machine value written to the ``choices`` sheet ``name`` column.
    label:
        Human readable text shown to the enumerator.
    extra:
        Additional passthrough columns for the choices sheet, e.g.
        translations (``label::French (fr)``) or cascading-select filter
        columns (``state``, ``county``).
    """

    name: str
    label: str
    extra: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, str]:
        out = {"name": self.name, "label": self.label}
        out.update(self.extra)
        return out


@dataclass
class ChoiceList:
    """A named list of :class:`Choice` used by ``select_one`` / ``select_multiple``."""

    list_name: str
    choices: List[Choice] = field(default_factory=list)

    def choice_names(self) -> List[str]:
        return [c.name for c in self.choices]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "list_name": self.list_name,
            "choices": [c.to_dict() for c in self.choices],
        }


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------
@dataclass
class Question:
    """A single questionnaire item.

    The object starts life partially populated (whatever the parser could
    extract) and is progressively enriched by the engine modules
    (classifier, variable generator, logic / constraint / calculation
    engines).  By the time it reaches the XLSForm builder every field that
    is needed for export has been filled in.
    """

    # --- as captured by the parser -------------------------------------
    raw_label: str = ""
    #: Free-text answer options captured from the source document.
    raw_choices: List[str] = field(default_factory=list)
    #: Natural-language skip / relevance instruction, e.g. "ask if yes".
    logic: str = ""
    #: Section / group the question belongs to.
    section: str = ""
    #: "group" (default) or "repeat" - how the section is emitted.
    section_type: str = "group"
    instruction: str = ""

    # --- resolved XLSForm fields ---------------------------------------
    name: str = ""
    xlsform_type: str = ""          # e.g. "select_one yes_no", "integer"
    label: str = ""
    hint: str = ""
    required: bool = False
    relevant: str = ""
    constraint: str = ""
    constraint_message: str = ""
    calculation: str = ""
    default: str = ""
    appearance: str = ""
    #: Cascading-select filter expression (XLSForm ``choice_filter`` column).
    choice_filter: str = ""
    #: Additional passthrough columns for the survey sheet, e.g. translations
    #: (``label::French (fr)``) or media columns (``media::image``).
    extra: Dict[str, str] = field(default_factory=dict)

    #: Populated for select questions: the list they reference.
    list_name: str = ""

    #: Provenance / audit trail entries (assumptions the engine made).
    assumptions: List[str] = field(default_factory=list)

    #: XLSForm type keywords that contain spaces and must not be split when
    #: deriving the base type (structural markers + SurveyCTO audit types).
    MULTIWORD_TYPES = (
        "begin group", "end group", "begin repeat", "end repeat",
        "text audit", "audio audit",
        "speed violations count", "speed violations list",
        "speed violations audit",
    )

    # -- convenience -----------------------------------------------------
    @property
    def base_type(self) -> str:
        """The bare type keyword, e.g. ``select_one`` from ``select_one yes_no``.

        Multi-word type keywords (``begin group``, ``text audit``, ...) are
        returned whole.
        """
        t = (self.xlsform_type or "").strip()
        for marker in self.MULTIWORD_TYPES:
            if t == marker or t.startswith(marker + " "):
                return marker
        return t.split(" ", 1)[0] if t else ""

    @property
    def is_select(self) -> bool:
        return self.base_type in ("select_one", "select_multiple")

    @property
    def references_choices(self) -> bool:
        """True for types whose second token names a choice list.

        Covers selects plus ``rank`` (ODK/Kobo), which also draws its items
        from the choices sheet.
        """
        return self.base_type in ("select_one", "select_multiple", "rank")

    @property
    def is_calculate(self) -> bool:
        return self.base_type == "calculate"

    @property
    def is_structural(self) -> bool:
        """True for begin/end group/repeat marker rows."""
        return self.base_type in STRUCTURAL_TYPES

    def add_assumption(self, message: str) -> None:
        if message and message not in self.assumptions:
            self.assumptions.append(message)

    # -- serialisation ---------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Question":
        """Build a Question from the flexible JSON input format.

        Accepts the friendly keys documented in the README, e.g.::

            {"question": "...", "type": "select_one", "choices": ["Yes", "No"]}
        """
        data = dict(data)  # shallow copy; do not mutate caller's dict
        raw_label = data.pop("question", data.pop("raw_label", data.pop("label", "")))
        raw_choices = data.pop("choices", data.pop("raw_choices", [])) or []
        # Normalise choices that arrive as {"name","label"} dicts to plain labels.
        norm_choices: List[str] = []
        for ch in raw_choices:
            if isinstance(ch, dict):
                norm_choices.append(str(ch.get("label", ch.get("name", ""))))
            else:
                norm_choices.append(str(ch))

        q = cls(raw_label=str(raw_label), raw_choices=norm_choices)
        # Map the remaining recognised keys directly onto the dataclass.
        recognised = {
            "type": "xlsform_type",
            "xlsform_type": "xlsform_type",
            "name": "name",
            "label": "label",
            "hint": "hint",
            "required": "required",
            "relevant": "relevant",
            "logic": "logic",
            "constraint": "constraint",
            "constraint_message": "constraint_message",
            "calculation": "calculation",
            "section": "section",
            "section_type": "section_type",
            "instruction": "instruction",
            "default": "default",
            "appearance": "appearance",
            "choice_filter": "choice_filter",
            "list_name": "list_name",
        }
        for key, attr in recognised.items():
            if key in data and data[key] is not None:
                setattr(q, attr, data[key])
        # ``"repeat": true`` marks the question's section as a repeat group.
        if data.get("repeat"):
            q.section_type = "repeat"
        # Translation / media passthrough columns, e.g. "label::French (fr)".
        for key, value in data.items():
            if "::" in key and value is not None:
                q.extra[key] = str(value)
        return q


# ---------------------------------------------------------------------------
# Settings & Questionnaire
# ---------------------------------------------------------------------------
@dataclass
class FormSettings:
    """Values written to the XLSForm ``settings`` sheet."""

    form_title: str = "Untitled Form"
    form_id: str = ""
    version: str = ""
    default_language: str = ""
    style: str = ""

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


@dataclass
class Questionnaire:
    """The complete parsed / compiled questionnaire.

    This is the single object passed between pipeline stages.
    """

    settings: FormSettings = field(default_factory=FormSettings)
    questions: List[Question] = field(default_factory=list)
    choice_lists: Dict[str, ChoiceList] = field(default_factory=dict)
    #: Optional free-form category / tag for the form (metadata only).
    category: str = "general"

    # -- choice list management -----------------------------------------
    def get_or_create_list(self, list_name: str) -> ChoiceList:
        if list_name not in self.choice_lists:
            self.choice_lists[list_name] = ChoiceList(list_name=list_name)
        return self.choice_lists[list_name]

    def add_choice_list(self, choice_list: ChoiceList) -> None:
        self.choice_lists[choice_list.list_name] = choice_list

    # -- serialisation ---------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "settings": self.settings.to_dict(),
            "category": self.category,
            "survey": [q.to_dict() for q in self.questions],
            "choices": {k: v.to_dict() for k, v in self.choice_lists.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Questionnaire":
        """Load a questionnaire from the JSON input format (Iteration 1)."""
        settings_data = data.get("settings", {}) or {}
        settings = FormSettings(
            form_title=settings_data.get("form_title", "Untitled Form"),
            form_id=settings_data.get("form_id", ""),
            version=settings_data.get("version", ""),
            default_language=settings_data.get("default_language", ""),
            style=settings_data.get("style", ""),
        )
        questions = [Question.from_dict(item) for item in data.get("survey", [])]
        q = cls(settings=settings, questions=questions,
                category=data.get("category", "general"))

        # Pre-defined choice lists may be supplied explicitly.
        for list_name, list_data in (data.get("choices", {}) or {}).items():
            cl = ChoiceList(list_name=list_name)
            raw = list_data.get("choices", list_data) if isinstance(list_data, dict) else list_data
            for ch in raw:
                if isinstance(ch, dict):
                    extra = {k: str(v) for k, v in ch.items()
                             if k not in ("name", "label") and v is not None}
                    cl.choices.append(Choice(name=str(ch.get("name", "")),
                                             label=str(ch.get("label", ch.get("name", ""))),
                                             extra=extra))
                else:
                    cl.choices.append(Choice(name=str(ch), label=str(ch)))
            q.add_choice_list(cl)
        return q
