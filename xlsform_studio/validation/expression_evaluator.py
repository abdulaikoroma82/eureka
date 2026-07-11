"""Lightweight tri-state XLSForm expression evaluator (for path analysis).

Purpose
-------
Evaluate the subset of ODK XPath used in ``relevant`` / ``constraint`` /
``calculation`` expressions against a *partial* assignment of variable
values, returning ``True``, ``False``, or ``None`` (unknown / cannot
evaluate). The static path analyzer uses this to walk every enumerator
path through a form: a relevant that evaluates ``False`` under a path's
assignment means the question is definitely skipped on that path.

Scope
-----
Deliberately small and dependency-free (no lxml, no XPath library):

* ``${name}`` references, resolved from the supplied assignment
* string literals (``'yes'``), numeric literals
* comparisons ``= != < <= > >=``
* boolean ``and`` / ``or`` with Kleene three-valued semantics
  (``False and None -> False``, ``True or None -> True``)
* arithmetic ``+ - * div mod`` (numeric results feed comparisons)
* functions: ``selected()``, ``not()``, ``true()``, ``false()``,
  ``today()``, ``once()``, ``string-length()``, ``count()``,
  ``coalesce()`` - everything else evaluates to unknown, never an error

Empty-value semantics mirror the device: a variable assigned
:data:`EMPTY` (its question was skipped / left blank) compares equal to
``''``, unequal to any non-empty literal, is never ``selected()``, and
has ``string-length() = 0``. A variable *absent* from the assignment is
unknown, so anything built on it is unknown too - the evaluator never
guesses.

Example
-------
>>> ev = ExpressionEvaluator()
>>> ev.evaluate("${resident} = '1'", {"resident": "1"})
True
>>> ev.evaluate("${resident} = '1'", {"resident": EMPTY})
False
>>> ev.evaluate("${resident} = '1'", {}) is None
True
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Union

#: Sentinel: the variable's question was reached but left blank / skipped -
#: its value on the device is the empty string.
EMPTY = object()

Tri = Optional[bool]                     # True / False / None(unknown)
Value = Union[str, float, None, object]  # a resolved operand

_TOKEN = re.compile(r"""
      (?P<ws>\s+)
    | (?P<ref>\$\{[A-Za-z_][A-Za-z0-9_]*\})
    | (?P<number>\d+(?:\.\d+)?)
    | (?P<string>'[^']*'|"[^"]*")
    | (?P<op><=|>=|!=|=|<|>|\+|-|\*)
    | (?P<lpar>\()
    | (?P<rpar>\))
    | (?P<comma>,)
    | (?P<dot>\.(?![\w.]))
    | (?P<word>[A-Za-z][\w:-]*)
""", re.VERBOSE)

_UNKNOWN = object()   # evaluation result: cannot determine


class _Parser:
    """Recursive-descent parser/evaluator over the token list.

    Evaluation happens during the parse (no AST): each grammar level
    returns a resolved :data:`Value`, where ``_UNKNOWN`` poisons any
    computation except three-valued and/or.
    """

    def __init__(self, tokens: List[tuple], values: Dict[str, Value]) -> None:
        self.tokens = tokens
        self.pos = 0
        self.values = values

    # -- token helpers ---------------------------------------------------
    def peek(self) -> tuple:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else ("eof", "")

    def next(self) -> tuple:
        tok = self.peek()
        self.pos += 1
        return tok

    def expect(self, kind: str) -> None:
        if self.next()[0] != kind:
            raise ValueError(f"expected {kind}")

    # -- grammar: or -> and -> comparison -> additive -> unary/primary ----
    def parse_or(self) -> Value:
        left = self.parse_and()
        while self.peek() == ("word", "or"):
            self.next()
            right = self.parse_and()
            left = self._kleene_or(self._truthy(left), self._truthy(right))
        return left

    def parse_and(self) -> Value:
        left = self.parse_comparison()
        while self.peek() == ("word", "and"):
            self.next()
            right = self.parse_comparison()
            left = self._kleene_and(self._truthy(left), self._truthy(right))
        return left

    def parse_comparison(self) -> Value:
        left = self.parse_additive()
        kind, text = self.peek()
        if kind == "op" and text in ("=", "!=", "<", "<=", ">", ">="):
            self.next()
            right = self.parse_additive()
            return self._compare(text, left, right)
        return left

    def parse_additive(self) -> Value:
        left = self.parse_primary()
        while True:
            kind, text = self.peek()
            if kind == "op" and text in ("+", "-", "*"):
                self.next()
                left = self._arith(text, left, self.parse_primary())
            elif kind == "word" and text in ("div", "mod"):
                self.next()
                left = self._arith(text, left, self.parse_primary())
            else:
                return left

    def parse_primary(self) -> Value:
        kind, text = self.next()
        if kind == "ref":
            name = text[2:-1]
            if name not in self.values:
                return _UNKNOWN
            val = self.values[name]
            return "" if val is EMPTY else val
        if kind == "number":
            return float(text)
        if kind == "string":
            return text[1:-1]
        if kind == "dot":
            return _UNKNOWN          # "." (self) - path analysis can't know it
        if kind == "op" and text == "-":
            operand = self.parse_primary()
            return -operand if isinstance(operand, float) else _UNKNOWN
        if kind == "lpar":
            inner = self.parse_or()
            self.expect("rpar")
            return inner
        if kind == "word":
            if self.peek()[0] == "lpar":
                return self._call(text)
            return _UNKNOWN          # bare word (unquoted literal etc.)
        raise ValueError(f"unexpected token {kind}:{text}")

    # -- function calls ----------------------------------------------------
    def _call(self, name: str) -> Value:
        self.expect("lpar")
        args: List[Value] = []
        if self.peek()[0] != "rpar":
            args.append(self.parse_or())
            while self.peek()[0] == "comma":
                self.next()
                args.append(self.parse_or())
        self.expect("rpar")

        if name == "true":
            return True
        if name == "false":
            return False
        if name == "not":
            t = self._truthy(args[0]) if args else None
            return (not t) if t is not None else _UNKNOWN
        if name == "selected":
            # selected(${multi}, 'code'): False when the multi-select is
            # known-empty; unknown otherwise (we never enumerate the 2^n
            # combinations of a multi-select).
            if args and args[0] == "":
                return False
            return _UNKNOWN
        if name == "string-length":
            if args and isinstance(args[0], str):
                return float(len(args[0]))
            return _UNKNOWN
        if name == "count":
            return _UNKNOWN          # node-set count needs runtime data
        if name in ("today", "once"):
            return _UNKNOWN          # value exists at runtime, unknowable now
        if name == "coalesce":
            for a in args:
                if a is _UNKNOWN:
                    return _UNKNOWN
                if a not in ("", None):
                    return a
            return ""
        return _UNKNOWN              # any other function: honest "don't know"

    # -- semantics ----------------------------------------------------------
    @staticmethod
    def _truthy(value: Value) -> Tri:
        if value is _UNKNOWN or value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, float):
            return value != 0
        return value != ""           # XPath string truthiness

    @staticmethod
    def _kleene_and(a: Tri, b: Tri) -> Tri:
        if a is False or b is False:
            return False
        if a is None or b is None:
            return None
        return True

    @staticmethod
    def _kleene_or(a: Tri, b: Tri) -> Tri:
        if a is True or b is True:
            return True
        if a is None or b is None:
            return None
        return False

    @staticmethod
    def _compare(op: str, left: Value, right: Value) -> Value:
        if left is _UNKNOWN or right is _UNKNOWN:
            return _UNKNOWN
        if isinstance(left, bool) or isinstance(right, bool):
            return _UNKNOWN          # comparing booleans: out of scope

        # Try numeric comparison first (XLSForm codes are strings but
        # numeric relationals coerce, e.g. ${age} > 5 with age = "12").
        def num(v: Value) -> Optional[float]:
            if isinstance(v, float):
                return v
            try:
                return float(str(v))
            except (TypeError, ValueError):
                return None

        ln, rn = num(left), num(right)
        if op in ("<", "<=", ">", ">="):
            if ln is None or rn is None:
                return False         # XPath: non-numeric relationals are false
            return {"<": ln < rn, "<=": ln <= rn,
                    ">": ln > rn, ">=": ln >= rn}[op]

        # Equality: numeric when both coerce, else string comparison.
        if ln is not None and rn is not None:
            equal = ln == rn
        else:
            equal = str(left) == str(right)
        return equal if op == "=" else not equal

    @staticmethod
    def _arith(op: str, left: Value, right: Value) -> Value:
        if not isinstance(left, float) or not isinstance(right, float):
            return _UNKNOWN
        try:
            return {"+": left + right, "-": left - right, "*": left * right,
                    "div": left / right, "mod": left % right}[op]
        except ZeroDivisionError:
            return _UNKNOWN


class ExpressionEvaluator:
    """Evaluate an XLSForm expression to True / False / None (unknown)."""

    def evaluate(self, expression: str,
                 values: Dict[str, Value]) -> Tri:
        """Evaluate *expression* under the partial assignment *values*.

        ``values`` maps variable name to its value on the current path:
        a string/number for an answered question, :data:`EMPTY` for one
        that is definitely blank. Variables absent from the mapping are
        unknown. Returns ``None`` whenever the truth can't be determined
        (including on any parse error - unparseable expressions are the
        syntax validator's job, not this one's).
        """
        expression = (expression or "").strip()
        if not expression:
            return None
        try:
            tokens = self._tokenize(expression)
            parser = _Parser(tokens, values)
            result = parser.parse_or()
            if parser.peek()[0] != "eof":
                return None          # trailing junk: don't guess
            return parser._truthy(result)
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _tokenize(expression: str) -> List[tuple]:
        tokens: List[tuple] = []
        pos = 0
        while pos < len(expression):
            m = _TOKEN.match(expression, pos)
            if m is None:
                raise ValueError(f"cannot tokenize at {pos}")
            pos = m.end()
            kind = m.lastgroup
            if kind != "ws":
                tokens.append((kind, m.group()))
        return tokens
