"""Advanced consistency validator (deterministic; Module D5).

Purpose
-------
Catch structural inconsistencies that are individually legal - every
expression parses, every reference resolves - but that make the *form as a
whole* wrong or wasteful. These are all graph/set properties, enumerable
and exactly decidable, so they belong to the rule layer, not AI:

* **Circular references** (error): question A's relevant/calculation
  depends on B while B depends on A - the form can never settle.
* **Contradictory conditions** (warning): a relevant like
  ``${x}='a' and ${x}='b'`` or ``${x} > 10 and ${x} < 5`` that no answer
  can ever satisfy - the question is unreachable.
* **Forward references** (warning): a condition that reads an answer
  collected *later* in the form. Engines tolerate it, but the question
  pops in and out retroactively - almost always an ordering mistake.
* **Unused calculations** (info): a ``calculate`` field whose result is
  never referenced anywhere - dead weight on every submission.
* **Empty groups** (warning): a ``begin group`` immediately closed by its
  ``end group`` - an orphan container that renders as a blank screen.
* **Near-identical choice lists** (info): two lists sharing most of their
  options - usually an accidental fork of one list (exact duplicates are
  consolidated automatically by the
  :mod:`~xlsform_studio.engine.choice_normalizer`; "near" ones need a
  human eye, so they are only flagged).

Inputs
------
A compiled :class:`~xlsform_studio.models.Questionnaire`.

Outputs
-------
A list of :class:`~xlsform_studio.validation.report_generator.Finding`
with category ``"consistency"``.

Example
-------
>>> from xlsform_studio.models import Questionnaire, Question
>>> qn = Questionnaire(questions=[
...     Question(name="a", label="A", xlsform_type="text",
...              relevant="${x_missing_is_logic_validators_job} != ''",
...              constraint=""),
...     Question(name="b", label="B", xlsform_type="text",
...              relevant="${b} = '1'")])
>>> ConsistencyValidator().validate(qn)  # doctest: +SKIP
"""

from __future__ import annotations

import re
from itertools import combinations
from typing import Dict, List, Set

from ..models import Questionnaire, REF_PATTERN
from .report_generator import Finding

_REF = REF_PATTERN
_EQ = re.compile(r"\$\{(\w+)\}\s*=\s*'([^']*)'")
_NUM_CMP = re.compile(r"\$\{(\w+)\}\s*(>=|<=|>|<)\s*(-?\d+(?:\.\d+)?)")
#: Overlap ratio above which two different lists are flagged as near-identical.
_NEAR_IDENTICAL = 0.8


class ConsistencyValidator:
    """Whole-form consistency checks (deterministic)."""

    def validate(self, questionnaire: Questionnaire) -> List[Finding]:
        findings: List[Finding] = []
        findings.extend(self._circular_references(questionnaire))
        findings.extend(self._contradictory_conditions(questionnaire))
        findings.extend(self._forward_references(questionnaire))
        findings.extend(self._unused_calculations(questionnaire))
        findings.extend(self._empty_groups(questionnaire))
        findings.extend(self._near_identical_lists(questionnaire))
        return findings

    # ------------------------------------------------------------------
    def _dependencies(self, qn: Questionnaire) -> Dict[str, Set[str]]:
        """name -> the names its relevant/calculation/choice_filter read."""
        names = {q.name for q in qn.questions if q.name}
        deps: Dict[str, Set[str]] = {}
        for q in qn.questions:
            if not q.name:
                continue
            refs: Set[str] = set()
            for expr in (q.relevant, q.calculation, q.choice_filter):
                refs.update(_REF.findall(expr or ""))
            deps[q.name] = (refs & names) - {q.name}
        return deps

    def _circular_references(self, qn: Questionnaire) -> List[Finding]:
        deps = self._dependencies(qn)
        findings: List[Finding] = []
        WHITE, GREY, BLACK = 0, 1, 2
        state = {name: WHITE for name in deps}
        reported: Set[frozenset] = set()

        def visit(name: str, path: List[str]) -> None:
            state[name] = GREY
            path.append(name)
            for dep in sorted(deps.get(name, ())):
                if state.get(dep) == GREY:
                    cycle = path[path.index(dep):] + [dep]
                    key = frozenset(cycle)
                    if key not in reported:
                        reported.add(key)
                        findings.append(Finding(
                            "error", "consistency",
                            f"Circular reference: {' -> '.join(cycle)}. "
                            f"These fields each wait on the other, so the "
                            f"form can never resolve their values.",
                            cycle[0]))
                elif state.get(dep) == WHITE:
                    visit(dep, path)
            path.pop()
            state[name] = BLACK

        for name in deps:
            if state[name] == WHITE:
                visit(name, [])
        return findings

    # ------------------------------------------------------------------
    def _contradictory_conditions(self, qn: Questionnaire) -> List[Finding]:
        findings: List[Finding] = []
        for q in qn.questions:
            expr = q.relevant or ""
            if not expr or " or " in expr.lower() or "not(" in expr.lower():
                continue        # only plain conjunctions are decidable here
            reason = (self._equality_contradiction(expr)
                      or self._numeric_contradiction(expr))
            if reason:
                findings.append(Finding(
                    "warning", "consistency",
                    f"Question '{q.name}' can never be shown: its condition "
                    f"`{expr}` is self-contradictory ({reason}).", q.name))
        return findings

    @staticmethod
    def _equality_contradiction(expr: str) -> str:
        wanted: Dict[str, str] = {}
        for var, value in _EQ.findall(expr):
            if var in wanted and wanted[var] != value:
                return (f"${{{var}}} would have to equal both "
                        f"'{wanted[var]}' and '{value}'")
            wanted[var] = value
        return ""

    @staticmethod
    def _numeric_contradiction(expr: str) -> str:
        lower: Dict[str, float] = {}
        upper: Dict[str, float] = {}
        for var, op, num in _NUM_CMP.findall(expr):
            value = float(num)
            if op in (">", ">="):
                bound = value if op == ">=" else value + 1e-9
                lower[var] = max(lower.get(var, bound), bound)
            else:
                bound = value if op == "<=" else value - 1e-9
                upper[var] = min(upper.get(var, bound), bound)
        for var in set(lower) & set(upper):
            if lower[var] > upper[var]:
                return (f"${{{var}}} would have to be both above and below "
                        f"the same value")
        return ""

    # ------------------------------------------------------------------
    def _forward_references(self, qn: Questionnaire) -> List[Finding]:
        real = [q for q in qn.questions if not q.is_structural and q.name]
        position = {q.name: i for i, q in enumerate(real)}
        findings: List[Finding] = []
        for q in real:
            for ref in sorted(set(_REF.findall(q.relevant or ""))):
                if ref in position and position[ref] > position[q.name]:
                    findings.append(Finding(
                        "warning", "consistency",
                        f"Question '{q.name}' is shown/hidden based on "
                        f"'{ref}', which is only asked later in the form - "
                        f"it will appear retroactively as answers change. "
                        f"Usually the questions are in the wrong order.",
                        q.name))
        return findings

    # ------------------------------------------------------------------
    def _unused_calculations(self, qn: Questionnaire) -> List[Finding]:
        used: Set[str] = set()
        for q in qn.questions:
            for expr in (q.relevant, q.constraint, q.calculation,
                         q.choice_filter, q.label, q.hint, q.default):
                used.update(_REF.findall(expr or ""))
        findings: List[Finding] = []
        for q in qn.questions:
            if q.is_calculate and q.name and q.name not in used:
                findings.append(Finding(
                    "info", "consistency",
                    f"Calculated field '{q.name}' is never referenced by "
                    f"any other field - if nothing downstream (or no "
                    f"analysis plan) needs it, it can be removed.", q.name))
        return findings

    # ------------------------------------------------------------------
    def _empty_groups(self, qn: Questionnaire) -> List[Finding]:
        findings: List[Finding] = []
        previous = None
        for q in qn.questions:
            if (previous is not None
                    and previous.base_type in ("begin group", "begin repeat")
                    and q.base_type == previous.base_type.replace("begin", "end")):
                findings.append(Finding(
                    "warning", "consistency",
                    f"Group '{previous.name or previous.label}' is empty - "
                    f"it opens and immediately closes, rendering as a blank "
                    f"screen.", previous.name))
            previous = q
        return findings

    # ------------------------------------------------------------------
    def _near_identical_lists(self, qn: Questionnaire) -> List[Finding]:
        findings: List[Finding] = []
        lists = list(qn.choice_lists.items())
        for (name_a, a), (name_b, b) in combinations(lists, 2):
            set_a = {(c.name, c.label) for c in a.choices}
            set_b = {(c.name, c.label) for c in b.choices}
            if not set_a or not set_b or set_a == set_b:
                continue        # exact duplicates are consolidated elsewhere
            overlap = len(set_a & set_b) / len(set_a | set_b)
            if overlap >= _NEAR_IDENTICAL:
                findings.append(Finding(
                    "info", "consistency",
                    f"Choice lists '{name_a}' and '{name_b}' share "
                    f"{overlap:.0%} of their options - if the difference is "
                    f"accidental, merge them so analysis sees one scale.",
                    name_a, confidence="heuristic"))
        return findings
