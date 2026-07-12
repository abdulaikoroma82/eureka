"""XLSForm expression syntax validator.

Purpose
-------
Deterministically check the *syntax* of every ``relevant``, ``constraint``,
``calculation`` and ``choice_filter`` expression in the form. This closes a
verified gap: pyxform converts the workbook to an XForm without parsing
expression internals (that is deferred to ODK Validate, a Java tool this
project deliberately does not bundle), so a malformed expression like
``. >< 5`` used to pass every check and only fail on the device.

What is checked
---------------
* balanced parentheses and quotes
* well-formed ``${...}`` references
* operator/operand alternation - catches doubled operators (``>< ``),
  missing operators (``${a} ${b}``), and dangling operators (``${a} >``)
* commas only inside function calls
* function names against the ODK XPath function catalogue (unknown names
  are a *warning* - platforms add functions over time - while structural
  breakage is an *error*)
* XPath path/predicate syntax used by cascading-select ``choice_filter``
  expressions, e.g. ``instance('cities')/root/item[state=${state}]`` -
  path steps (``/``, ``//``), attribute axes (``@id``), wildcards (``*``)
  and predicates (``[...]``) are accepted as first-class grammar, not just
  the flat comparison expressions ``relevant``/``constraint`` use

Inputs
------
A compiled :class:`~xlsform_studio.models.Questionnaire`.

Outputs
-------
A list of :class:`~xlsform_studio.validation.report_generator.Finding`.

Example
-------
>>> from xlsform_studio.models import Questionnaire, Question
>>> qn = Questionnaire(questions=[Question(name="s", xlsform_type="integer",
...                                         label="S", constraint=". >< 5")])
>>> any(f.level == "error" for f in ExpressionValidator().validate(qn))
True
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from ..models import Questionnaire
from .report_generator import Finding

# ODK XPath functions accepted across the supported platforms.
_KNOWN_FUNCTIONS = {
    # logic / selection
    "if", "not", "true", "false", "boolean", "boolean-from-string",
    "selected", "selected-at", "count-selected", "jr:choice-name",
    "coalesce", "once", "checklist", "weighted-checklist",
    # numbers
    "number", "int", "round", "sum", "max", "min", "abs", "pow", "exp",
    "exp10", "log", "log10", "sqrt", "random", "count", "position",
    "count-non-empty",
    # strings
    "string", "concat", "join", "substr", "string-length", "contains",
    "starts-with", "ends-with", "translate", "normalize-space", "regex",
    "uuid", "digest", "lower-case", "upper-case",
    # dates & times
    "today", "now", "date", "date-time", "decimal-date-time", "decimal-time",
    "format-date", "format-date-time",
    # repeats / instances
    "indexed-repeat", "instance", "current", "randomize",
    # geo
    "distance", "area",
    # misc
    "version", "property", "pulldata",
}

# Word tokens that act as binary operators in ODK XPath.
_WORD_OPERATORS = {"and", "or", "div", "mod"}

_TOKEN = re.compile(r"""
      (?P<ws>\s+)
    | (?P<ref>\$\{[A-Za-z_][A-Za-z0-9_]*\})
    | (?P<badref>\$\{?[^\s}]*\}?)
    | (?P<number>\d+(?:\.\d+)?)
    | (?P<string>'[^']*'|"[^"]*")
    | (?P<op>!=|<=|>=|=|<|>|\+|\*|-)
    | (?P<lparen>\()
    | (?P<rparen>\))
    | (?P<comma>,)
    | (?P<lbracket>\[)
    | (?P<rbracket>\])
    | (?P<at>@)
    | (?P<slash>//?)
    | (?P<dots>\.\.|\.)
    | (?P<name>[A-Za-z][A-Za-z0-9_:-]*)
""", re.VERBOSE)

_EXPRESSION_COLUMNS = ("relevant", "constraint", "calculation", "choice_filter")


class ExpressionValidator:
    """Syntax-check every logic expression in the form."""

    def validate(self, questionnaire: Questionnaire) -> List[Finding]:
        findings: List[Finding] = []
        for q in questionnaire.questions:
            for column in _EXPRESSION_COLUMNS:
                expr = (getattr(q, column, "") or "").strip()
                if not expr:
                    continue
                error, unknown_funcs = self.check(expr)
                if error:
                    findings.append(Finding(
                        "error", "expression",
                        f"Malformed {column} on '{q.name}': {error} "
                        f"(expression: `{expr}`)", q.name))
                for fn in unknown_funcs:
                    findings.append(Finding(
                        "warning", "expression",
                        f"Unrecognised function '{fn}()' in {column} on "
                        f"'{q.name}' - check it is supported on your target "
                        f"platform.", q.name, confidence="unsupported"))
        return findings

    # ------------------------------------------------------------------
    def check(self, expr: str) -> Tuple[Optional[str], List[str]]:
        """Return (error_message_or_None, unknown_function_names)."""
        # Unbalanced quotes are unrecoverable for the tokenizer - check first.
        if expr.count("'") % 2 or expr.count('"') % 2:
            return "unbalanced quote", []

        tokens = self._tokenize(expr)
        if isinstance(tokens, str):        # tokenizer error message
            return tokens, []

        return self._parse(tokens, expr)

    # ------------------------------------------------------------------
    def _tokenize(self, expr: str):
        tokens = []
        pos = 0
        while pos < len(expr):
            m = _TOKEN.match(expr, pos)
            if not m:
                return f"unexpected character '{expr[pos]}' at position {pos}"
            pos = m.end()
            kind = m.lastgroup
            if kind == "ws":
                continue
            if kind == "badref":
                return f"malformed field reference '{m.group()}'"
            tokens.append((kind, m.group()))
        return tokens

    def _parse(self, tokens: list, expr: str) -> Tuple[Optional[str], List[str]]:
        """Operand/operator alternation with paren & call tracking."""
        unknown: List[str] = []
        expect_operand = True
        paren_stack: List[str] = []      # "call" or "group"
        prev_name_was_func = False

        i = 0
        while i < len(tokens):
            kind, text = tokens[i]
            next_kind = tokens[i + 1][0] if i + 1 < len(tokens) else None

            if kind == "name":
                low = text.lower()
                # Word operators (and/or/div/mod) are never function names -
                # check them before the call branch so "x) and (y" parses.
                if low in _WORD_OPERATORS:
                    if expect_operand:
                        return (f"operator '{text}' where a value was expected", unknown)
                    expect_operand = True
                    i += 1
                    continue
                if next_kind == "lparen":
                    # function call
                    if not expect_operand:
                        return (f"missing operator before function '{text}'", unknown)
                    if low not in _KNOWN_FUNCTIONS and not low.startswith("jr:"):
                        unknown.append(text)
                    prev_name_was_func = True
                    i += 1
                    continue
                # bare name: treat as a node reference (rare but legal XPath)
                if not expect_operand:
                    return (f"missing operator before '{text}'", unknown)
                expect_operand = False
                i += 1
                continue

            if kind in ("ref", "number", "string", "dots"):
                if not expect_operand:
                    return (f"missing operator before '{text}'", unknown)
                expect_operand = False
                i += 1
                continue

            if kind == "op":
                if expect_operand:
                    # unary minus on a value is fine; anything else is not
                    if text == "-" and next_kind in ("ref", "number", "dots",
                                                     "lparen", "name"):
                        i += 1
                        continue
                    # a bare '*' where an operand is expected is the XPath
                    # wildcard node-test (e.g. 'foo/*'), not multiplication
                    if text == "*":
                        expect_operand = False
                        i += 1
                        continue
                    return (f"operator '{text}' where a value was expected", unknown)
                expect_operand = True
                i += 1
                continue

            if kind == "slash":
                # path step separator ('/' or '//') - valid both as the
                # start of an absolute path and between existing steps
                expect_operand = True
                i += 1
                continue

            if kind == "at":
                # attribute axis, e.g. '@id' - must be followed by a name
                if not expect_operand:
                    return (f"missing operator before '{text}'", unknown)
                i += 1
                continue

            if kind == "lbracket":
                if expect_operand:
                    return ("predicate '[' where a value was expected", unknown)
                paren_stack.append("predicate")
                expect_operand = True
                i += 1
                continue

            if kind == "rbracket":
                if not paren_stack or paren_stack[-1] != "predicate":
                    return ("unbalanced ']'", unknown)
                if expect_operand:
                    return ("expression ends with an operator before ']'", unknown)
                paren_stack.pop()
                expect_operand = False
                i += 1
                continue

            if kind == "lparen":
                if prev_name_was_func:
                    paren_stack.append("call")
                    prev_name_was_func = False
                else:
                    if not expect_operand:
                        return ("missing operator before '('", unknown)
                    paren_stack.append("group")
                expect_operand = True
                i += 1
                continue

            if kind == "rparen":
                if not paren_stack:
                    return ("unbalanced ')'", unknown)
                if paren_stack[-1] == "predicate":
                    return ("mismatched ')' - expected ']' to close predicate",
                            unknown)
                # zero-argument calls like today() close while expecting operand
                closing_call = paren_stack[-1] == "call"
                if expect_operand and not (closing_call and
                                           tokens[i - 1][0] == "lparen"):
                    return ("expression ends with an operator before ')'", unknown)
                paren_stack.pop()
                expect_operand = False
                i += 1
                continue

            if kind == "comma":
                if "call" not in paren_stack:
                    return ("comma outside a function call", unknown)
                if expect_operand:
                    return ("empty function argument before ','", unknown)
                expect_operand = True
                i += 1
                continue

            return (f"unexpected token '{text}'", unknown)

        if paren_stack:
            if paren_stack[-1] == "predicate":
                return ("unbalanced '['", unknown)
            return ("unbalanced '('", unknown)
        if expect_operand and tokens:
            return ("expression ends with an operator", unknown)
        return (None, unknown)
