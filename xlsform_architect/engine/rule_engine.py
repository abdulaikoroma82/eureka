"""Rule engine orchestrator.

Purpose
-------
The "Rule Engine" box of the architecture.  It runs the individual engine
modules in the correct order over a whole :class:`Questionnaire`:

    1. Variable naming        (Module 3)
    2. Question classification (Module 2)
    3. Choice-list building    (via ChoicesBuilder inputs)
    4. Logic compilation       (Module 5)
    5. Constraint attachment   (Module 6)
    6. Calculation generation  (Module 7)

Inputs
------
A raw :class:`~xlsform_architect.models.Questionnaire` (from any parser or the
JSON loader).

Outputs
-------
The same questionnaire, fully enriched and ready for the XLSForm builders,
plus a flat list of assumption strings for the assumption log.

Example
-------
>>> from xlsform_architect.models import Questionnaire, Question
>>> qn = Questionnaire(questions=[
...     Question(raw_label="Is the child enrolled in OTP?", raw_choices=["Yes", "No"]),
...     Question(raw_label="Admission date", logic="ask if yes")])
>>> engine = RuleEngine()
>>> qn, notes = engine.compile(qn)
>>> qn.questions[0].name
'child_enrolled_otp'
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from ..models import Choice, Question, Questionnaire
from .calculation_engine import CalculationEngine
from .constraint_engine import ConstraintEngine
from .knowledge_base import KnowledgeBase
from .logic_engine import LogicEngine
from .question_classifier import QuestionClassifier
from .variable_generator import VariableGenerator

_NON_WORD = re.compile(r"[^0-9a-zA-Z]+")


class RuleEngine:
    """Deterministic questionnaire compiler."""

    def __init__(self, knowledge: Optional[KnowledgeBase] = None) -> None:
        self.kb = knowledge or KnowledgeBase.load()
        self.namer = VariableGenerator(self.kb)
        self.classifier = QuestionClassifier(self.kb)
        self.logic = LogicEngine(self.kb)
        self.constraints = ConstraintEngine(self.kb)
        self.calculator = CalculationEngine(self.kb)

    # ------------------------------------------------------------------
    def compile(self, questionnaire: Questionnaire,
                add_calculations: bool = True) -> Tuple[Questionnaire, List[str]]:
        """Enrich *questionnaire* in place and return (questionnaire, notes)."""
        self.namer.reset()

        # Seed the standard shared choice lists (yes_no).
        self._seed_standard_lists(questionnaire)

        # Pass 1: names + types + choice lists.
        for q in questionnaire.questions:
            self._name(q)
            self._resolve_list_name(q, questionnaire)
            self.classifier.classify(q, list_name=q.list_name or None)
            self._materialise_choices(q, questionnaire)
            self._default_label(q)

        # Pass 2: logic (needs neighbouring names) + constraints.
        for idx, q in enumerate(questionnaire.questions):
            previous = questionnaire.questions[idx - 1] if idx > 0 else None
            self.logic.resolve(q, previous=previous, known=questionnaire.questions)
            self.constraints.apply(q)

        # Pass 3: derived calculations.
        if add_calculations:
            for calc in self.calculator.build(questionnaire):
                self.namer.register(calc.name)
                questionnaire.questions.append(calc)

        return questionnaire, self._collect_notes(questionnaire)

    # ------------------------------------------------------------------
    def _name(self, q: Question) -> None:
        if q.name:
            # Sanitise & register an explicit name.
            clean = self.namer.generate(q.raw_label or q.name, preferred=q.name)
            q.name = clean
        else:
            q.name = self.namer.generate(q.raw_label)

    def _default_label(self, q: Question) -> None:
        if not q.label:
            q.label = (q.raw_label or q.name).strip()
        if not q.hint and q.instruction:
            q.hint = q.instruction.strip()

    def _resolve_list_name(self, q: Question, qn: Questionnaire) -> None:
        """Give select questions a meaningful list name derived from the label."""
        if not q.raw_choices and q.base_type not in ("select_one", "select_multiple"):
            return
        if q.list_name:
            return
        # An explicit type like "select_one mylist" (or "rank mylist") already
        # names the list - honour it so the supplied choices are materialised
        # under that name.
        parts = (q.xlsform_type or "").split()
        if len(parts) >= 2 and parts[0] in ("select_one", "select_multiple", "rank"):
            q.list_name = parts[1]
            return
        # Yes/No is handled by the classifier; here derive from the variable.
        cfg = self.kb.yes_no()
        if self._is_yes_no(q.raw_choices, cfg):
            return
        base = q.name or "list"
        list_name = f"{base}_opts"
        # Ensure uniqueness against existing lists with different contents.
        q.list_name = list_name

    def _materialise_choices(self, q: Question, qn: Questionnaire) -> None:
        """Create Choice rows for a select/rank question's raw options."""
        if not q.references_choices or not q.raw_choices:
            return
        list_name = q.list_name
        if not list_name:
            return
        cl = qn.get_or_create_list(list_name)
        if cl.choices:  # already populated (shared/predefined list)
            return
        used: set = set()
        for opt in q.raw_choices:
            name = self._unique_choice_name(self._choice_name(opt), used)
            used.add(name)
            cl.choices.append(Choice(name=name, label=str(opt).strip()))

    def _seed_standard_lists(self, qn: Questionnaire) -> None:
        # Always ensure the shared, standard yes_no list exists.
        cfg = self.kb.yes_no()
        yn_name = cfg.get("list_name", "yes_no")
        if yn_name not in qn.choice_lists:
            cl = qn.get_or_create_list(yn_name)
            for ch in cfg.get("choices", []):
                cl.choices.append(Choice(name=str(ch["name"]), label=str(ch["label"])))

    # ------------------------------------------------------------------
    @staticmethod
    def _choice_name(option: str) -> str:
        text = str(option).strip().lower()
        slug = _NON_WORD.sub("_", text).strip("_")
        if not slug:
            slug = "opt"
        if slug[0].isdigit():
            # numeric codes are valid choice names; keep as-is
            return slug
        return slug[:40]

    @staticmethod
    def _unique_choice_name(name: str, used: set) -> str:
        if name not in used:
            return name
        counter = 2
        candidate = f"{name}_{counter}"
        while candidate in used:
            counter += 1
            candidate = f"{name}_{counter}"
        return candidate

    @staticmethod
    def _is_yes_no(choices, cfg) -> bool:
        if len(choices) != 2:
            return False
        pos = {t.lower() for t in cfg.get("positive_tokens", [])}
        neg = {t.lower() for t in cfg.get("negative_tokens", [])}
        norm = {c.strip().lower() for c in choices}
        return bool(norm & pos) and bool(norm & neg)

    @staticmethod
    def _collect_notes(qn: Questionnaire) -> List[str]:
        notes: List[str] = []
        for q in qn.questions:
            for a in q.assumptions:
                notes.append(f"[{q.name or q.raw_label[:30]}] {a}")
        return notes
