"""Interview simulator - walk a compiled form the way a device would.

Purpose
-------
Testing a questionnaire's logic by eye is slow and error-prone: you have
to trace every ``relevant`` by hand, imagine each ``constraint`` firing,
and mentally run the ``calculation`` columns. This engine *runs* the form
instead. Given answers, it does exactly what ODK Collect / Enketo would:

* **Skips** - re-evaluates every ``relevant`` against the answers so far
  and hides (or reveals) questions live.
* **Constraints** - checks the ``constraint`` when an answer is submitted,
  with ``.`` bound to the candidate value, and rejects it with the
  ``constraint_message`` instead of recording it.
* **Calculations** - recomputes ``calculate`` fields as their inputs
  change and surfaces the running values.
* **Repeats** - lets a repeat group be instantiated any number of times,
  each instance with its own answers and its own scope.

It is a pure, deterministic engine (no UI, no I/O): the CLI ``--simulate``
mode and the Streamlit "Run Interview Simulation" panel are thin drivers
over it, and the tests script it directly. All expression evaluation goes
through :class:`~xlsform_studio.validation.expression_evaluator.
RuntimeEvaluator`, the same concrete evaluator the rest of the tool trusts.

Model
-----
The compiled form is normalized into a flat node stream (questions plus
explicit group/repeat boundaries) regardless of whether the source used
structural ``begin/end`` rows or section attributes. A cursor walks the
stream; a stack of :class:`_Frame` objects tracks open repeat instances so
each question reads and writes the right scope (a nested repeat sees its
outer repeat's answers, never vice versa).

Example
-------
>>> from xlsform_studio.models import Questionnaire, Question, Choice, ChoiceList
>>> qn = Questionnaire(
...     questions=[Question(name="age", label="Age?", xlsform_type="integer",
...                         constraint=". >= 0 and . <= 120")])
>>> sim = Interview(qn)
>>> sim.current().question.name
'age'
>>> sim.submit("200").ok
False
>>> sim.submit("30").ok
True
>>> sim.current().kind
'done'
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..models import Choice, Question, Questionnaire
from ..validation.expression_evaluator import RuntimeEvaluator

# Node kinds in the normalized stream.
_Q, _BG, _EG, _BR, _ER = "q", "begin_group", "end_group", "begin_repeat", "end_repeat"


@dataclass
class _Node:
    kind: str
    question: Optional[Question] = None      # for _Q
    name: str = ""                           # group/repeat name
    label: str = ""                          # human label (repeat prompt)
    relevant: str = ""                       # group/repeat-level relevance
    match: int = -1                          # BEGIN -> index of its END
    repeat_owner: int = -1                   # index of enclosing begin_repeat, or -1


@dataclass
class _Frame:
    """One open repeat, with a private answer store per instance."""
    node_index: int
    body_start: int
    end_index: int
    name: str
    label: str
    instances: List[Dict[str, str]] = field(default_factory=lambda: [{}])
    current: int = 0

    @property
    def store(self) -> Dict[str, str]:
        return self.instances[self.current]


@dataclass
class Step:
    """What the driver should do next."""
    kind: str                                # "question" | "repeat_prompt" | "done"
    question: Optional[Question] = None
    choices: List[Choice] = field(default_factory=list)
    repeat_name: str = ""
    repeat_label: str = ""
    completed_instances: int = 0             # for a repeat_prompt
    path: str = ""                           # breadcrumb, e.g. "Household 2"


@dataclass
class SubmitResult:
    ok: bool
    error: str = ""


@dataclass
class Answer:
    name: str
    label: str
    value: str
    path: str = ""


@dataclass
class Calculation:
    name: str
    label: str
    value: str
    path: str = ""


@dataclass
class SimEvent:
    kind: str                                # answered|skipped|rejected|repeat_added|repeat_closed
    label: str
    detail: str = ""


class Interview:
    """A live, deterministic walk through a compiled questionnaire."""

    def __init__(self, questionnaire: Questionnaire) -> None:
        self.qn = questionnaire
        self.evaluator = RuntimeEvaluator()
        self.nodes = _normalize(questionnaire)
        self.top: Dict[str, str] = {}
        self.stack: List[_Frame] = []
        self.cursor = 0
        self.answered: List[Answer] = []
        self.skipped: List[Answer] = []
        self.events: List[SimEvent] = []
        self._advance()

    # ------------------------------------------------------------------
    # Public driver API
    # ------------------------------------------------------------------
    def current(self) -> Step:
        """The next thing to do: answer a question, decide on a repeat, or
        finish."""
        if self.cursor >= len(self.nodes):
            return Step(kind="done")
        node = self.nodes[self.cursor]
        if node.kind == _ER:
            frame = self.stack[-1]
            return Step(kind="repeat_prompt", repeat_name=frame.name,
                        repeat_label=frame.label,
                        completed_instances=frame.current + 1,
                        path=self._path())
        q = node.question
        return Step(kind="question", question=q,
                    choices=self._choices(q), path=self._path())

    def submit(self, value: str) -> SubmitResult:
        """Answer the current question. Rejected (constraint/required) answers
        are not recorded; the same question stays current."""
        step = self.current()
        if step.kind != "question":
            raise RuntimeError("current step is not a question")
        q = step.question
        value = (value or "").strip()

        error = self._check(q, value)
        if error:
            self.events.append(SimEvent("rejected", q.label or q.name, error))
            return SubmitResult(ok=False, error=error)

        self._store(q.name, value)
        self.answered.append(Answer(q.name, q.label or q.name, value, self._path()))
        self.events.append(SimEvent("answered", q.label or q.name,
                                    self._display(q, value)))
        self.cursor += 1
        self._recompute()
        self._advance()
        return SubmitResult(ok=True)

    def add_repeat_instance(self) -> None:
        """At a repeat prompt, add another instance and re-enter the body."""
        frame = self._require_repeat_prompt()
        frame.instances.append({})
        frame.current = len(frame.instances) - 1
        self.events.append(SimEvent("repeat_added", frame.label,
                                    f"instance {frame.current + 1}"))
        self.cursor = frame.body_start
        self._advance()

    def finish_repeat(self) -> None:
        """At a repeat prompt, close the repeat and continue past it."""
        frame = self._require_repeat_prompt()
        self.events.append(SimEvent("repeat_closed", frame.label,
                                    f"{len(frame.instances)} instance(s)"))
        self.stack.pop()
        self.cursor = frame.end_index + 1
        self._recompute()
        self._advance()

    def state(self) -> "InterviewState":
        """A snapshot for the live side panel."""
        return InterviewState(
            answered=list(self.answered),
            skipped=list(self.skipped),
            calculations=self._calculations(),
            events=list(self.events),
            path=self._path(),
            done=self.cursor >= len(self.nodes))

    def restart(self) -> None:
        self.__init__(self.qn)

    # ------------------------------------------------------------------
    # Walk
    # ------------------------------------------------------------------
    def _advance(self) -> None:
        """Move the cursor to the next actionable node (a visible question,
        a repeat prompt, or the end), skipping hidden questions and blocks
        and computing calculations as they are passed."""
        while self.cursor < len(self.nodes):
            node = self.nodes[self.cursor]

            if node.kind == _Q:
                q = node.question
                if not self._relevant(q.relevant):
                    self._skip(q)
                    self.cursor += 1
                    continue
                if q.is_calculate:
                    self._eval_calc(node)
                    self.cursor += 1
                    continue
                return                                  # a question to ask

            if node.kind in (_BG, _BR):
                if not self._relevant(node.relevant):
                    self.cursor = node.match + 1        # skip whole block
                    continue
                if node.kind == _BR:
                    self.stack.append(_Frame(
                        node_index=self.cursor,
                        body_start=self.cursor + 1,
                        end_index=node.match,
                        name=node.name, label=node.label))
                self.cursor += 1
                continue

            if node.kind == _EG:
                self.cursor += 1
                continue

            if node.kind == _ER:
                return                                  # ask "add another?"

    # ------------------------------------------------------------------
    # Evaluation helpers
    # ------------------------------------------------------------------
    def _scope(self) -> Dict[str, str]:
        merged = dict(self.top)
        for frame in self.stack:
            merged.update(frame.store)
        return merged

    def _relevant(self, expr: str) -> bool:
        return self.evaluator.truthy(expr, self._scope(), default=True)

    def _check(self, q: Question, value: str) -> str:
        if q.required and not value:
            return "This question is required."
        if not value:
            return ""                                   # blank + optional: fine
        if q.references_choices and not q.is_calculate:
            valid = {c.name for c in self._choices(q)}
            given = value.split() if q.base_type == "select_multiple" else [value]
            unknown = [g for g in given if g not in valid]
            if valid and unknown:
                return (f"'{', '.join(unknown)}' is not an option for this "
                        f"question.")
        if q.constraint and not self.evaluator.truthy(
                q.constraint, self._scope(), self_value=value, default=True):
            return q.constraint_message or "The answer violates a constraint."
        return ""

    def _store(self, name: str, value: str) -> None:
        (self.stack[-1].store if self.stack else self.top)[name] = value

    def _eval_calc(self, node: _Node) -> None:
        q = node.question
        value = self.evaluator.compute(q.calculation, self._scope())
        self._store(q.name, value)

    def _recompute(self) -> None:
        """Re-evaluate every calculation currently in scope (a couple of
        passes so chained calculations settle), so displayed values track
        the latest answers."""
        for _ in range(2):
            for i, node in enumerate(self.nodes):
                if node.kind != _Q or not node.question.is_calculate:
                    continue
                if not self._calc_in_scope(node):
                    continue
                if not self._relevant(node.question.relevant):
                    continue
                self._store_for(node, node.question.name,
                                self.evaluator.compute(node.question.calculation,
                                                       self._scope()))

    def _calc_in_scope(self, node: _Node) -> bool:
        """A calculation is current if it is top-level or its enclosing
        repeat is currently open."""
        if node.repeat_owner < 0:
            return True
        return any(f.node_index == node.repeat_owner for f in self.stack)

    def _store_for(self, node: _Node, name: str, value: str) -> None:
        if node.repeat_owner < 0:
            self.top[name] = value
            return
        for frame in self.stack:
            if frame.node_index == node.repeat_owner:
                frame.store[name] = value
                return

    def _skip(self, q: Question) -> None:
        self._store(q.name, "")                         # blank on the device
        if not q.is_calculate:
            self.skipped.append(Answer(q.name, q.label or q.name, "",
                                       self._path()))
            self.events.append(SimEvent(
                "skipped", q.label or q.name,
                f"hidden by: {q.relevant}" if q.relevant else "hidden"))

    def _calculations(self) -> List[Calculation]:
        out: List[Calculation] = []
        scope = self._scope()
        for node in self.nodes:
            if node.kind != _Q or not node.question.is_calculate:
                continue
            if not self._calc_in_scope(node):
                continue
            q = node.question
            out.append(Calculation(q.name, q.label or q.name,
                                   scope.get(q.name, ""), self._path()))
        return out

    # ------------------------------------------------------------------
    def _choices(self, q: Question) -> List[Choice]:
        if not q.references_choices:
            return []
        cl = self.qn.choice_lists.get(q.choice_list_name)
        return list(cl.choices) if cl else []

    def _display(self, q: Question, value: str) -> str:
        """Render an answer for the event log (choice codes -> labels)."""
        if not value:
            return "(blank)"
        cl = self.qn.choice_lists.get(q.choice_list_name) if q.references_choices else None
        if cl:
            labels = {c.name: c.label for c in cl.choices}
            return ", ".join(labels.get(v, v) for v in value.split())
        return value

    def _path(self) -> str:
        return " › ".join(f"{f.label} {f.current + 1}" for f in self.stack)

    def _require_repeat_prompt(self) -> _Frame:
        if self.cursor >= len(self.nodes) or self.nodes[self.cursor].kind != _ER:
            raise RuntimeError("current step is not a repeat prompt")
        return self.stack[-1]


@dataclass
class InterviewState:
    answered: List[Answer]
    skipped: List[Answer]
    calculations: List[Calculation]
    events: List[SimEvent]
    path: str
    done: bool


# ---------------------------------------------------------------------------
# Normalization: compiled form -> flat node stream (both grouping styles).
# ---------------------------------------------------------------------------
def _normalize(qn: Questionnaire) -> List[_Node]:
    nodes: List[_Node] = (_from_structural(qn.questions)
                          if any(q.is_structural for q in qn.questions)
                          else _from_sections(qn.questions))
    _match_and_scope(nodes)
    return nodes


def _from_structural(questions: List[Question]) -> List[_Node]:
    nodes: List[_Node] = []
    for q in questions:
        bt = q.base_type
        if bt == "begin group":
            nodes.append(_Node(_BG, name=q.name, label=q.label or q.name,
                               relevant=q.relevant or ""))
        elif bt == "end group":
            nodes.append(_Node(_EG))
        elif bt == "begin repeat":
            nodes.append(_Node(_BR, name=q.name, label=q.label or q.name,
                               relevant=q.relevant or ""))
        elif bt == "end repeat":
            nodes.append(_Node(_ER))
        elif q.name:
            nodes.append(_Node(_Q, question=q))
    return nodes


def _from_sections(questions: List[Question]) -> List[_Node]:
    nodes: List[_Node] = []
    current: Optional[str] = None
    kind = "group"
    for q in questions:
        if not q.name and not (q.section or "").strip():
            continue
        section = (q.section or "").strip()
        if section != current:
            if current:
                nodes.append(_Node(_EG if kind == "group" else _ER))
            if section:
                kind = "repeat" if q.section_type == "repeat" else "group"
                nodes.append(_Node(_BG if kind == "group" else _BR,
                                   name=section, label=section))
            current = section
        if q.name:
            nodes.append(_Node(_Q, question=q))
    if current:
        nodes.append(_Node(_EG if kind == "group" else _ER))
    return nodes


def _match_and_scope(nodes: List[_Node]) -> None:
    """Pair each BEGIN with its END and tag every node with the index of its
    enclosing repeat (for calculation scoping)."""
    open_blocks: List[int] = []
    repeat_stack: List[int] = []
    for i, node in enumerate(nodes):
        node.repeat_owner = repeat_stack[-1] if repeat_stack else -1
        if node.kind in (_BG, _BR):
            open_blocks.append(i)
            if node.kind == _BR:
                repeat_stack.append(i)
        elif node.kind in (_EG, _ER):
            if open_blocks:
                nodes[open_blocks.pop()].match = i
            if node.kind == _ER and repeat_stack:
                repeat_stack.pop()
