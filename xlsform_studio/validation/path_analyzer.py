"""Static path analysis (runtime reference-resolution checks).

Purpose
-------
The other validators check each expression in isolation: syntax is valid,
references point at questions that exist. None of them ask the runtime
question: *when this expression executes on the device, will the variable
it references actually hold a value on every path an enumerator can take
through the form?* A calculation referencing a question inside a skipped
group passes every static check, deploys, and then misbehaves in the
field. This module closes that gap without running the form: it
enumerates the possible paths implied by ``relevant`` conditions and
tracks, per path, which variables are definitely filled, possibly filled,
or definitely empty.

Findings
--------
* **error** ``path_analysis``: an expression references a variable that is
  *definitely empty* on at least one path where the expression runs.
* **error**: a question is unreachable on every path (contradictory
  ``relevant`` chain).
* **error**: an expression references a variable that exists nowhere in
  the form, or one that lives inside a repeat the expression can't see
  (inner-repeat variables are out of scope outside their repeat;
  outer variables remain in scope inside nested repeats).
* **warning**: a referenced variable is only *possibly* filled where the
  expression runs (not-required questions, multi-selects, calculations
  built on ``today()``/``once()``/other volatile functions).
* **warning**: a ``required`` question has a ``relevant`` condition - the
  required rule won't fire on paths that skip it.
* **warning**: a question is reachable on fewer than 5% of paths
  (near-dead - usually a logic error).

Approach
--------
Paths branch on **decision variables**: ``select_one`` questions whose
answer some ``relevant`` expression references (one branch per choice,
plus a blank branch when the question isn't required). Conditions on
variables we can't enumerate (integers, text) evaluate to *unknown* via
the three-valued :class:`~xlsform_studio.validation.expression_evaluator.
ExpressionEvaluator`, which degrades the affected fill-states to
"possibly" - the analysis never guesses. If full enumeration would exceed
:data:`MAX_PATHS`, it falls back to a single conservative pass (logged,
and noted in the report) that may over-report warnings but cannot miss
the reference errors, which are path-independent.

Example
-------
>>> from xlsform_studio.models import Questionnaire, Question
>>> qn = Questionnaire(questions=[
...     Question(name="a", label="A", xlsform_type="integer")])
>>> PathAnalyzer().validate(qn)
[]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..logging_config import get_logger
from ..models import Questionnaire, REF_PATTERN
from .expression_evaluator import EMPTY, ExpressionEvaluator
from .report_generator import Finding

_log = get_logger("validation.path_analyzer")

_REF = REF_PATTERN

#: Above this many enumerated paths, switch to the conservative single-pass
#: approximation (see module docstring).
MAX_PATHS = 10_000

#: Reachable on fewer than this fraction of paths -> "near-dead" warning.
NEAR_DEAD_FRACTION = 0.05

#: Volatile functions: a calculation built on these has a value that can't
#: be predicted statically, so anything referencing it is "possibly filled".
_VOLATILE = re.compile(r"\b(today|now|once|random|uuid)\s*\(")

# Fill states, ordered weakest to strongest.
_EMPTY, _POSSIBLY, _FILLED = 0, 1, 2


@dataclass
class _Q:
    """One analyzable question with its effective (group-conjoined) logic."""

    name: str
    base_type: str
    relevant: str                    # effective: own AND enclosing groups'
    required: bool
    scope: Tuple[str, ...]           # enclosing repeat names, outermost first
    choices: List[str] = field(default_factory=list)   # select_one values
    calculation: str = ""
    constraint: str = ""
    choice_filter: str = ""

    def expressions(self) -> List[Tuple[str, str]]:
        out = []
        if self.calculation:
            out.append(("calculation", self.calculation))
        if self.constraint:
            out.append(("constraint", self.constraint))
        if self.choice_filter:
            out.append(("choice_filter", self.choice_filter))
        return out


class PathAnalyzer:
    """Enumerate enumerator paths and verify runtime reference resolution."""

    def __init__(self) -> None:
        self.evaluator = ExpressionEvaluator()
        #: True when the last run used the conservative approximation.
        self.approximated = False

    # ------------------------------------------------------------------
    def validate(self, questionnaire: Questionnaire) -> List[Finding]:
        self.approximated = False
        qs = self._prepare(questionnaire)
        if not qs:
            return []
        findings: List[Finding] = []

        # --- path-independent checks ---------------------------------
        names = {q.name for q in qs}
        scopes = {q.name: q.scope for q in qs}
        findings.extend(self._check_references(qs, names, scopes))
        findings.extend(self._check_required_skippable(qs))

        # --- path enumeration -----------------------------------------
        paths = self._enumerate(qs)
        if paths is None:
            self.approximated = True
            _log.warning("path enumeration exceeded %d paths; using the "
                        "conservative approximation", MAX_PATHS)
            findings.append(Finding(
                "info", "path_analysis",
                f"The form's skip logic implies more than {MAX_PATHS:,} "
                f"distinct paths; path analysis used a conservative "
                f"approximation (reference errors are still fully checked; "
                f"some warnings below may be over-cautious)."))
            findings.extend(self._conservative(qs, names))
            return findings

        findings.extend(self._check_paths(qs, paths))
        return findings

    # ------------------------------------------------------------------
    # Preparation: effective relevance, repeat scopes, choice domains
    # ------------------------------------------------------------------
    def _prepare(self, qn: Questionnaire) -> List[_Q]:
        out: List[_Q] = []
        group_stack: List[str] = []      # relevant of enclosing begin-groups
        repeat_stack: List[str] = []     # names of enclosing begin-repeats
        for q in qn.questions:
            if q.is_structural:
                base = q.base_type
                if base in ("begin group", "begin repeat"):
                    group_stack.append(q.relevant or "")
                    if base == "begin repeat":
                        repeat_stack.append(q.name or f"repeat{len(out)}")
                elif base in ("end group", "end repeat"):
                    if group_stack:
                        group_stack.pop()
                    if base == "end repeat" and repeat_stack:
                        repeat_stack.pop()
                continue
            if not q.name:
                continue

            conjuncts = [r for r in group_stack if r]
            if q.relevant:
                conjuncts.append(q.relevant)
            effective = (" and ".join(f"({c})" for c in conjuncts)
                         if len(conjuncts) > 1 else
                         (conjuncts[0] if conjuncts else ""))

            # Attribute-style repeats (sections compiled to repeats at
            # export) scope their members like structural repeats do.
            scope = tuple(repeat_stack)
            if not scope and q.section and q.section_type == "repeat":
                scope = (q.section,)

            choices: List[str] = []
            if q.base_type == "select_one":
                cl = qn.choice_lists.get(q.choice_list_name)
                if cl:
                    choices = [c.name for c in cl.choices]

            out.append(_Q(name=q.name, base_type=q.base_type,
                          relevant=effective, required=q.required,
                          scope=scope, choices=choices,
                          calculation=q.calculation or "",
                          constraint=q.constraint or "",
                          choice_filter=q.choice_filter or ""))
        return out

    # ------------------------------------------------------------------
    # Path-independent checks
    # ------------------------------------------------------------------
    def _check_references(self, qs: List[_Q], names: set,
                          scopes: Dict[str, Tuple[str, ...]]) -> List[Finding]:
        findings: List[Finding] = []
        for q in qs:
            for kind, expr in q.expressions() + ([("relevant", q.relevant)]
                                                 if q.relevant else []):
                for ref in dict.fromkeys(_REF.findall(expr)):
                    if ref == q.name:
                        continue
                    if ref not in names:
                        findings.append(Finding(
                            "error", "path_analysis",
                            f"The {kind} of '{q.name}' references "
                            f"'${{{ref}}}', which does not exist anywhere "
                            f"in the form.", q.name))
                        continue
                    # Repeat scoping: the referenced variable's repeat path
                    # must be a prefix of the referencing question's (outer
                    # or same repeat = visible; inner or sibling = not).
                    ref_scope = scopes[ref]
                    if ref_scope and ref_scope != q.scope[:len(ref_scope)]:
                        findings.append(Finding(
                            "error", "path_analysis",
                            f"The {kind} of '{q.name}' references "
                            f"'${{{ref}}}', which lives inside repeat "
                            f"'{ref_scope[-1]}' - repeat variables are not "
                            f"in scope outside their repeat (use "
                            f"indexed-repeat() or move the logic inside).",
                            q.name))
        return findings

    def _check_required_skippable(self, qs: List[_Q]) -> List[Finding]:
        findings = []
        for q in qs:
            if q.required and q.relevant:
                findings.append(Finding(
                    "warning", "path_analysis",
                    f"'{q.name}' is required but has a relevant condition "
                    f"(`{q.relevant}`) - on paths where the condition is "
                    f"false the question is skipped and the required rule "
                    f"never fires. Fine if intentional; analysis must not "
                    f"assume this variable is always present.", q.name))
        return findings

    # ------------------------------------------------------------------
    # Exact path enumeration
    # ------------------------------------------------------------------
    def _enumerate(self, qs: List[_Q]) -> Optional[List[Tuple[dict, dict]]]:
        """Return [(assignment, fill)] per path, or None past MAX_PATHS."""
        decision_vars = set()
        for q in qs:
            decision_vars.update(_REF.findall(q.relevant))

        paths: List[Tuple[dict, dict]] = [({}, {})]
        for q in qs:
            new_paths: List[Tuple[dict, dict]] = []
            for assignment, fill in paths:
                shown = (self.evaluator.evaluate(q.relevant, assignment)
                         if q.relevant else True)
                if shown is False:
                    assignment = dict(assignment)
                    fill = dict(fill)
                    fill[q.name] = _EMPTY
                    assignment[q.name] = EMPTY   # its value is '' downstream
                    new_paths.append((assignment, fill))
                    continue

                state = self._fill_state(q, shown, fill)
                branch = (shown is True and q.name in decision_vars
                          and q.choices)
                if not branch:
                    fill = dict(fill)
                    fill[q.name] = state
                    new_paths.append((assignment, fill))
                    continue

                values = list(q.choices) + ([EMPTY] if not q.required else [])
                for value in values:
                    a2, f2 = dict(assignment), dict(fill)
                    a2[q.name] = value
                    f2[q.name] = _EMPTY if value is EMPTY else _FILLED
                    new_paths.append((a2, f2))

            if len(new_paths) > MAX_PATHS:
                return None
            paths = new_paths
        return paths

    @staticmethod
    def _fill_state(q: _Q, shown, fill: dict) -> int:
        if q.base_type == "calculate":
            if shown is None or _VOLATILE.search(q.calculation):
                return _POSSIBLY      # volatile inputs: value unpredictable
            refs = _REF.findall(q.calculation)
            # A calculation over inputs that are all definitely filled on
            # this path is itself filled; any weaker input weakens it.
            if all(fill.get(r) == _FILLED for r in refs):
                return _FILLED
            return _POSSIBLY
        if shown is None:
            return _POSSIBLY          # may be skipped - unknown condition
        return _FILLED if q.required else _POSSIBLY

    # ------------------------------------------------------------------
    def _check_paths(self, qs: List[_Q],
                     paths: List[Tuple[dict, dict]]) -> List[Finding]:
        findings: List[Finding] = []
        total = len(paths)

        # Reachability per question.
        reachable_counts = {q.name: 0 for q in qs}
        for _, fill in paths:
            for name, state in fill.items():
                if state != _EMPTY:
                    reachable_counts[name] = reachable_counts.get(name, 0) + 1

        for q in qs:
            reached = reachable_counts.get(q.name, 0)
            if q.relevant and reached == 0:
                findings.append(Finding(
                    "error", "path_analysis",
                    f"'{q.name}' is unreachable: its relevant condition "
                    f"(`{q.relevant}`) is false on every possible path - "
                    f"the conditions contradict each other.", q.name))
            elif (q.relevant and total >= 20
                  and reached / total < NEAR_DEAD_FRACTION):
                findings.append(Finding(
                    "warning", "path_analysis",
                    f"'{q.name}' is reachable on only {reached} of {total} "
                    f"paths ({reached / total:.1%}) - a near-dead question "
                    f"is usually a logic error.", q.name))

        # Reference fill-state per path. Report each (question, kind, ref)
        # once at its worst observed severity.
        worst: Dict[Tuple[str, str, str], int] = {}
        for assignment, fill in paths:
            for q in qs:
                if fill.get(q.name) == _EMPTY:
                    continue          # skipped questions don't evaluate
                for kind, expr in q.expressions():
                    for ref in dict.fromkeys(_REF.findall(expr)):
                        if ref == q.name or ref not in fill:
                            continue
                        state = fill[ref]
                        key = (q.name, kind, ref)
                        worst[key] = min(worst.get(key, _FILLED), state)

        for (name, kind, ref), state in worst.items():
            if state == _EMPTY:
                findings.append(Finding(
                    "error", "path_analysis",
                    f"The {kind} of '{name}' references '${{{ref}}}', "
                    f"which is definitely empty on at least one path where "
                    f"the {kind} runs (the referenced question is skipped "
                    f"there). Guard the expression (e.g. coalesce(), or "
                    f"matching relevant conditions) or the form will "
                    f"misbehave on-device.", name))
            elif state == _POSSIBLY:
                findings.append(Finding(
                    "warning", "path_analysis",
                    f"The {kind} of '{name}' references '${{{ref}}}', "
                    f"which is only possibly filled on some paths "
                    f"(not-required question, multi-select, or a volatile "
                    f"calculation) - verify the {kind} tolerates a blank "
                    f"value.", name))
        return findings

    # ------------------------------------------------------------------
    # Conservative approximation (used past MAX_PATHS)
    # ------------------------------------------------------------------
    def _conservative(self, qs: List[_Q], names: set) -> List[Finding]:
        """Single symbolic pass: no enumeration, so nothing is *definitely*
        empty - every conditional/unrequired variable is treated as
        possibly empty wherever an expression that doesn't share its
        condition references it. Over-reports warnings; the reference
        errors were already fully checked path-independently."""
        findings: List[Finding] = []
        relevant_of = {q.name: q.relevant for q in qs}
        state_of = {q.name: (_FILLED if q.required and not q.relevant
                             and q.base_type != "calculate" else _POSSIBLY)
                    for q in qs}
        for q in qs:
            for kind, expr in q.expressions():
                for ref in dict.fromkeys(_REF.findall(expr)):
                    if ref == q.name or ref not in names:
                        continue
                    if state_of[ref] == _FILLED:
                        continue
                    # Referencing something conditional from an expression
                    # whose own condition doesn't textually include it may
                    # hit a blank; flag for manual verification.
                    if relevant_of[ref] and relevant_of[ref] in (q.relevant or ""):
                        continue      # same guard is (at least) present
                    findings.append(Finding(
                        "warning", "path_analysis",
                        f"The {kind} of '{q.name}' references '${{{ref}}}', "
                        f"which may be empty when the {kind} runs "
                        f"(conservative check - path enumeration was "
                        f"skipped on this large form). Verify manually.",
                        q.name))
        return findings

