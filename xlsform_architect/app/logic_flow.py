"""Skip-pattern flowchart builder (visual logic map).

Purpose
-------
Turn the compiled form's ``relevant`` expressions into a *picture* of the
skip pattern, in three renderings of the same graph:

* **ASCII branch tree** - embedded in ``logic_map.md``, readable anywhere::

      resident — Are you a resident of this district?
      ├── Yes → years_lived
      └── otherwise → respondent_age

* **Graphviz DOT** - written as ``logic_flow.dot`` in the output package
  (open with any Graphviz tool, or paste into an online viewer).
* **Interactive chart** - the same DOT string rendered live in the app's
  Logic map tab via Streamlit's built-in graphviz component (no system
  Graphviz install needed - it renders in the browser).

The graph is *derived*, never authored: every edge comes from a ``${ref}``
inside a question's ``relevant`` expression (an edge from the referenced
question to the conditional one, labelled with the condition). Conditions
are prettified for humans - ``${resident}='1'`` renders as ``Yes`` by
looking the code up in the question's choice list - while the raw
expressions stay authoritative in the XLSForm itself and in the logic-map
tables.

Inputs
------
A compiled :class:`~xlsform_architect.models.Questionnaire`.

Outputs
-------
:meth:`LogicFlowBuilder.edges` (the graph), :meth:`~LogicFlowBuilder.
to_ascii` (branch tree text), :meth:`~LogicFlowBuilder.to_dot` (DOT source).
All empty/"" when the form has no skip logic.

Example
-------
>>> from xlsform_architect.models import Questionnaire, Question
>>> qn = Questionnaire(questions=[
...     Question(name="a", label="A?", xlsform_type="integer"),
...     Question(name="b", label="B?", xlsform_type="text", relevant="${a} > 5")])
>>> [ (e.source, e.target, e.condition) for e in LogicFlowBuilder().edges(qn) ]
[('a', 'b', 'a > 5')]
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List

from ..models import Question, Questionnaire

_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_NOT_EQ = re.compile(r"not\(\s*\$\{(\w+)\}\s*=\s*'([^']*)'\s*\)")
_SELECTED = re.compile(r"selected\(\s*\$\{(\w+)\}\s*,\s*'([^']*)'\s*\)")
_CMP = re.compile(r"\$\{(\w+)\}\s*(!=|>=|<=|=|>|<)\s*'([^']*)'")

#: Longest node/edge label before truncation (keeps the chart readable).
_MAX_LABEL = 42


@dataclass
class LogicEdge:
    """One dependency: *target* is only shown when *condition* on *source* holds."""

    source: str          # question whose answer is referenced
    target: str          # question gated by the condition
    condition: str       # prettified, e.g. "resident = Yes"
    raw: str             # the target's raw relevant expression
    #: True when the condition references only this source (lets renderers
    #: shorten "resident = Yes" to "Yes" under the resident node).
    sole_source: bool = True


class LogicFlowBuilder:
    """Derive and render the skip-pattern graph of a compiled form."""

    # ------------------------------------------------------------------
    def edges(self, questionnaire: Questionnaire) -> List[LogicEdge]:
        names = {q.name for q in questionnaire.questions if q.name}
        out: List[LogicEdge] = []
        for q in questionnaire.questions:
            if q.is_structural or not q.relevant or not q.name:
                continue
            refs = [r for r in dict.fromkeys(_REF.findall(q.relevant))
                    if r in names and r != q.name]
            pretty = self._prettify(q.relevant, questionnaire)
            for ref in refs:
                out.append(LogicEdge(source=ref, target=q.name,
                                     condition=pretty, raw=q.relevant,
                                     sole_source=len(refs) == 1))
        return out

    # ------------------------------------------------------------------
    # ASCII branch tree
    # ------------------------------------------------------------------
    def to_ascii(self, questionnaire: Questionnaire) -> str:
        edges = self.edges(questionnaire)
        if not edges:
            return ""

        real = [q for q in questionnaire.questions if not q.is_structural]
        position = {q.name: i for i, q in enumerate(real)}
        by_source: Dict[str, List[LogicEdge]] = {}
        for e in edges:
            by_source.setdefault(e.source, []).append(e)

        blocks: List[str] = []
        for q in real:
            group = by_source.get(q.name)
            if not group:
                continue
            lines = [f"{q.name} — {self._short(q.label or q.raw_label)}"]

            # One branch per distinct condition, in first-seen order.
            branches: Dict[str, List[str]] = {}
            for e in group:
                label = self._branch_label(e, q.name)
                branches.setdefault(label, []).append(e.target)

            gated = {t for ts in branches.values() for t in ts}
            otherwise = next(
                (r.name for r in real[position[q.name] + 1:]
                 if r.name not in gated), None)

            rows = [f"{label} → {', '.join(ts)}"
                    for label, ts in branches.items()]
            rows.append(f"otherwise → {otherwise or '(end of form)'}")
            for i, row in enumerate(rows):
                connector = "└──" if i == len(rows) - 1 else "├──"
                lines.append(f"{connector} {row}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    # ------------------------------------------------------------------
    # Graphviz DOT
    # ------------------------------------------------------------------
    def to_dot(self, questionnaire: Questionnaire) -> str:
        edges = self.edges(questionnaire)
        if not edges:
            return ""

        by_name = {q.name: q for q in questionnaire.questions}
        involved = [q for q in questionnaire.questions if not q.is_structural
                    and q.name in ({e.source for e in edges}
                                   | {e.target for e in edges})]

        lines = [
            "digraph skip_logic {",
            "  rankdir=TB;",
            "  bgcolor=transparent;",
            '  node [shape=box, style="rounded,filled", fillcolor="#eef3f8",'
            ' color="#5b7c99", fontname="Helvetica", fontsize=10];',
            '  edge [fontname="Helvetica", fontsize=9, color="#5b7c99",'
            ' fontcolor="#33566e"];',
        ]
        for q in involved:
            label = self._short(q.label or q.raw_label)
            lines.append(f'  "{q.name}" '
                         f'[label="{self._esc(q.name)}\\n{self._esc(label)}"];')
        for e in edges:
            source_q = by_name.get(e.source)
            label = self._branch_label(e, e.source) if source_q else e.condition
            lines.append(f'  "{e.source}" -> "{e.target}" '
                         f'[label="{self._esc(label)}"];')
        lines.append("}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Condition prettifying
    # ------------------------------------------------------------------
    def describe_condition(self, expr: str, qn: Questionnaire) -> str:
        """Public helper: render an expression for humans (used by the
        enumerator guide and other documentation artefacts)."""
        return self._prettify(expr, qn)

    def _prettify(self, expr: str, qn: Questionnaire) -> str:
        by_name = {q.name: q for q in qn.questions}

        def label_for(name: str, code: str) -> str:
            q = by_name.get(name)
            if q is not None:
                cl = qn.choice_lists.get(self._list_name(q))
                if cl:
                    for c in cl.choices:
                        if c.name == code:
                            return c.label
            return code

        out = _NOT_EQ.sub(lambda m: f"{m[1]} ≠ {label_for(m[1], m[2])}", expr)
        out = _SELECTED.sub(
            lambda m: f"{m[1]} includes {label_for(m[1], m[2])}", out)
        out = _CMP.sub(
            lambda m: f"{m[1]} {'≠' if m[2] == '!=' else m[2]} "
                      f"{label_for(m[1], m[3])}", out)
        out = _REF.sub(lambda m: m[1], out)
        return " ".join(out.split())

    def _branch_label(self, edge: LogicEdge, source: str) -> str:
        """Shorten "resident = Yes" to "Yes" when shown at the resident node."""
        label = edge.condition
        if not edge.sole_source:
            return label
        if label.startswith(f"{source} = "):
            return label[len(source) + 3:]
        if label.startswith(f"{source} "):
            return label[len(source) + 1:]
        return label

    # ------------------------------------------------------------------
    @staticmethod
    def _list_name(q: Question) -> str:
        parts = (q.xlsform_type or "").split()
        return parts[1] if len(parts) >= 2 else q.list_name

    @staticmethod
    def _short(text: str) -> str:
        text = " ".join(text.split())
        return text if len(text) <= _MAX_LABEL else text[:_MAX_LABEL - 1] + "…"

    @staticmethod
    def _esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace('"', '\\"')
