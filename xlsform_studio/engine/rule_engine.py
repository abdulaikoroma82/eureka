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
A raw :class:`~xlsform_studio.models.Questionnaire` (from any parser or the
JSON loader).

Outputs
-------
The same questionnaire, fully enriched and ready for the XLSForm builders,
plus a flat list of assumption strings for the assumption log.

Example
-------
>>> from xlsform_studio.models import Questionnaire, Question
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

        # Pass 1: names + types + choice lists.  Structural rows (explicit
        # begin/end group/repeat markers) pass through untouched.
        for q in questionnaire.questions:
            if q.is_structural:
                if q.name:
                    self.namer.register(q.name)
                else:
                    q.name = self.namer.generate(q.label or q.raw_label or "grp")
                continue
            self._name(q)
            self._resolve_list_name(q, questionnaire)
            self.classifier.classify(q, list_name=q.list_name or None)
            self._materialise_choices(q, questionnaire)
            self._default_label(q)

        # Pass 1b: share identical choice lists (e.g. repeated Likert scales).
        self._deduplicate_choice_lists(questionnaire)

        # Pass 1c: add "please specify" follow-ups after Other options.
        self._inject_other_specify(questionnaire)

        # Pass 2: logic (needs neighbouring names) + constraints.
        for idx, q in enumerate(questionnaire.questions):
            if q.is_structural:
                continue
            previous = self._previous_real(questionnaire.questions, idx)
            self.logic.resolve(q, previous=previous, known=questionnaire.questions)
            self.constraints.apply(q)

        # Pass 3: derived calculations. Each is inserted directly after the
        # last question it references (not appended at the end) so a
        # calculation over a repeat variable stays inside that repeat.
        if add_calculations:
            for calc in self.calculator.build(questionnaire):
                self.namer.register(calc.name)
                refs = set(re.findall(r"\$\{(\w+)\}", calc.calculation))
                insert_at = max(
                    (i + 1 for i, q in enumerate(questionnaire.questions)
                     if q.name in refs), default=len(questionnaire.questions))
                questionnaire.questions.insert(insert_at, calc)

        return questionnaire, self._collect_notes(questionnaire)

    # ------------------------------------------------------------------
    @staticmethod
    def _previous_real(questions: List[Question], idx: int) -> Optional[Question]:
        """The nearest preceding non-structural question, if any."""
        for j in range(idx - 1, -1, -1):
            if not questions[j].is_structural:
                return questions[j]
        return None

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
            # "code=Label" options (from the parser's coded-option pattern)
            # keep the author's code as the stored choice name.
            coded = re.match(r"^([A-Za-z0-9_]{1,10})=(.+)$", str(opt))
            if coded:
                name = self._unique_choice_name(coded.group(1), used)
                label = coded.group(2).strip()
            else:
                name = self._unique_choice_name(self._choice_name(opt), used)
                label = str(opt).strip()
            used.add(name)
            cl.choices.append(Choice(name=name, label=label))

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

    # ------------------------------------------------------------------
    def _deduplicate_choice_lists(self, qn: Questionnaire) -> None:
        """Merge auto-generated lists with identical options into one.

        Repeated scales (e.g. the same Likert options on many questions)
        otherwise produce one list per question, bloating the choices sheet.
        Only auto-generated lists (``*_opts``) are merged; explicitly named
        lists are respected as deliberate.
        """
        by_content: dict = {}
        remap: dict = {}
        for list_name, cl in qn.choice_lists.items():
            key = tuple((c.name, c.label) for c in cl.choices)
            if not key:
                continue
            if key in by_content and list_name.endswith("_opts"):
                remap[list_name] = by_content[key]
            else:
                by_content.setdefault(key, list_name)

        if not remap:
            return
        for q in qn.questions:
            if not q.references_choices:
                continue
            parts = q.xlsform_type.split()
            current = parts[1] if len(parts) >= 2 else q.list_name
            if current in remap:
                shared = remap[current]
                q.xlsform_type = f"{parts[0]} {shared}"
                q.list_name = shared
                q.add_assumption(
                    f"Options identical to list '{shared}'; shared it instead "
                    f"of duplicating.")
        for old in remap:
            qn.choice_lists.pop(old, None)

    # ------------------------------------------------------------------
    def _inject_other_specify(self, qn: Questionnaire) -> None:
        """Add a text follow-up after selects that offer an Other option."""
        insertions: List[tuple] = []
        for idx, q in enumerate(qn.questions):
            if not q.is_select:
                continue
            cl = qn.choice_lists.get(q.list_name or "")
            if cl is None and q.xlsform_type.split()[1:]:
                cl = qn.choice_lists.get(q.xlsform_type.split()[1])
            if cl is None:
                continue
            other = next((c for c in cl.choices
                          if c.name == "other" or
                          c.label.strip().lower().startswith("other")), None)
            if other is None:
                continue
            # Skip if a follow-up already exists.
            follow_name = f"{q.name}_other"
            if any(x.name == follow_name for x in qn.questions):
                continue
            follow = Question(
                raw_label=f"Please specify other ({q.label or q.raw_label})",
                name=self.namer.generate("", preferred=follow_name),
                xlsform_type="text",
                label="Please specify other",
                relevant=f"selected(${{{q.name}}}, '{other.name}')",
                section=q.section, section_type=q.section_type)
            follow.add_assumption(
                f"'Other' option detected on '{q.name}'; added a specify "
                f"follow-up shown only when Other is selected.")
            insertions.append((idx + 1, follow))

        for offset, (idx, follow) in enumerate(insertions):
            qn.questions.insert(idx + offset, follow)

    @staticmethod
    def _collect_notes(qn: Questionnaire) -> List[str]:
        notes: List[str] = []
        for q in qn.questions:
            for a in q.assumptions:
                notes.append(f"[{q.name or q.raw_label[:30]}] {a}")
        return notes
