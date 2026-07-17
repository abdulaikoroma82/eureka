"""XLSForm expression evaluator - shared lexer/grammar, two resolvers.

This module hosts one small, dependency-free (no lxml, no XPath library)
recursive-descent evaluator for the subset of ODK XPath used in
``relevant`` / ``constraint`` / ``calculation`` expressions. The tokenizer
and grammar are shared; two *resolver* strategies plug in the differing
semantics:

* :class:`ExpressionEvaluator` (**static**, tri-state) - used by the path
  analyzer. Evaluates against a *partial* assignment and returns ``True``,
  ``False``, or ``None`` (unknown). ``.`` (self), ``today()`` and a
  multi-select whose membership can't be enumerated all resolve to
  *unknown*, which propagates via Kleene three-valued ``and``/``or`` so
  the analyzer never guesses.
* :class:`RuntimeEvaluator` (**concrete**) - used by the interview
  simulator. Every variable has a real answer, so it resolves ``.`` to the
  candidate value, ``today()``/``now()`` to the actual date, and
  ``selected()`` / ``count-selected()`` against the concrete multi-select
  string, returning real values rather than "unknown".

Shared scope: ``${name}`` references, string/number literals, comparisons
(``= != < <= > >=``), boolean ``and`` / ``or``, arithmetic
(``+ - * div mod``), and the common functions ``not selected true false
today now once string-length count count-selected coalesce int number
round if``. Anything outside this subset evaluates to unknown (static) or
blank (runtime), never an error.

Empty-value semantics mirror the device: a variable assigned :data:`EMPTY`
(reached but blank) compares equal to ``''`` and is never ``selected()``.

Example
-------
>>> ExpressionEvaluator().evaluate("${resident} = '1'", {"resident": "1"})
True
>>> ExpressionEvaluator().evaluate("${resident} = '1'", {}) is None
True
>>> RuntimeEvaluator().truthy("${resident} = '1'", {"resident": "1"})
True
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Dict, List, Optional, Union

#: Sentinel: the variable's question was reached but left blank / skipped -
#: its value on the device is the empty string.
EMPTY = object()

#: Evaluation result: the truth/value cannot be determined (static resolver).
_UNKNOWN = object()

Tri = Optional[bool]                     # True / False / None(unknown)
Value = Union[str, float, bool, None, object]

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

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Shared value semantics (module-level so both resolvers and the parser use
# the same rules).
# ---------------------------------------------------------------------------
def _truthy(value: Value) -> Tri:
    if value is _UNKNOWN or value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value != 0
    return value != ""                   # XPath string truthiness


def _kleene_and(a: Tri, b: Tri) -> Tri:
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


def _kleene_or(a: Tri, b: Tri) -> Tri:
    if a is True or b is True:
        return True
    if a is None or b is None:
        return None
    return False


def _num(v: Value) -> Optional[float]:
    if isinstance(v, float):
        return v
    try:
        return float(str(v))
    except (TypeError, ValueError):
        return None


def _compare(op: str, left: Value, right: Value) -> Value:
    if left is _UNKNOWN or right is _UNKNOWN:
        return _UNKNOWN
    if isinstance(left, bool) or isinstance(right, bool):
        return _UNKNOWN                  # comparing booleans: out of scope

    ln, rn = _num(left), _num(right)
    if op in ("<", "<=", ">", ">="):
        if ln is None or rn is None:
            return False                 # XPath: non-numeric relationals are false
        return {"<": ln < rn, "<=": ln <= rn,
                ">": ln > rn, ">=": ln >= rn}[op]

    # Equality: numeric when both coerce, else string comparison.
    if ln is not None and rn is not None:
        equal = ln == rn
    else:
        equal = str(left) == str(right)
    return equal if op == "=" else not equal


def _arith(op: str, left: Value, right: Value) -> Value:
    # Coerce numeric strings (answers are stored as strings, e.g. "12"),
    # but leave unknown/blank/non-numeric operands unknown.
    if isinstance(left, bool) or isinstance(right, bool):
        return _UNKNOWN
    ln, rn = _num(left), _num(right)
    if ln is None or rn is None:
        return _UNKNOWN
    try:
        return {"+": ln + rn, "-": ln - rn, "*": ln * rn,
                "div": ln / rn, "mod": ln % rn}[op]
    except ZeroDivisionError:
        return _UNKNOWN


#: Hard ceilings so a hostile expression (from an imported XLSForm or an AI
#: draft) can never exhaust the tokenizer's memory or blow the recursive
#: descent parser's stack. A real XLSForm expression is far below these.
_MAX_EXPR_LEN = 4000
_MAX_PARSE_DEPTH = 100


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


# ---------------------------------------------------------------------------
# Resolvers: the only behaviour that differs between static and runtime.
# ---------------------------------------------------------------------------
class _StaticResolver:
    """Tri-state resolution for the path analyzer (conservative)."""

    def __init__(self, values: Dict[str, Value]) -> None:
        self.values = values

    def ref(self, name: str) -> Value:
        if name not in self.values:
            return _UNKNOWN
        val = self.values[name]
        return "" if val is EMPTY else val

    def self_value(self) -> Value:
        return _UNKNOWN                  # "." - path analysis can't know it

    def call(self, name: str, args: List[Value]) -> Value:
        if name == "not":
            t = _truthy(args[0]) if args else None
            return (not t) if t is not None else _UNKNOWN
        if name == "selected":
            # False only when the multi-select is known-empty; otherwise
            # unknown (never enumerate the 2^n combinations).
            if args and args[0] == "":
                return False
            return _UNKNOWN
        if name in ("string-length",):
            if args and isinstance(args[0], str):
                return float(len(args[0]))
            return _UNKNOWN
        if name in ("today", "now", "once", "count", "count-selected"):
            return _UNKNOWN              # runtime-only values
        return _shared_call(name, args)


class _RuntimeResolver:
    """Concrete resolution for the interview simulator.

    Missing/blank references resolve to ``""`` (an unanswered question is
    blank on the device), and date-shaped values are coerced to an ordinal
    so date relationals (``. <= today()``, ``${end} >= ${start}``) work.
    """

    def __init__(self, values: Dict[str, Value], self_value: Value = "") -> None:
        self.values = values
        self._self = self_value

    def ref(self, name: str) -> Value:
        val = self.values.get(name, "")
        return _coerce(val)

    def self_value(self) -> Value:
        return _coerce(self._self)

    def call(self, name: str, args: List[Value]) -> Value:
        if name == "not":
            return not _truthy(args[0]) if args else True
        if name == "selected":
            multi = "" if (not args or args[0] in ("", _UNKNOWN)) else str(args[0])
            code = str(args[1]) if len(args) > 1 else ""
            return code in multi.split()
        if name == "count-selected":
            multi = "" if (not args or args[0] in ("", _UNKNOWN)) else str(args[0])
            return float(len(multi.split()))
        if name == "string-length":
            return float(len(_text(args[0]))) if args else 0.0
        if name in ("today", "now"):
            return float(_dt.date.today().toordinal())
        if name == "once":
            return args[0] if args else ""
        if name == "count":
            return _UNKNOWN              # node-set count: no repeat model here
        return _shared_call(name, args)


def _shared_call(name: str, args: List[Value]) -> Value:
    """Functions whose result is the same in both resolvers."""
    if name == "true":
        return True
    if name == "false":
        return False
    if name == "coalesce":
        for a in args:
            if a is _UNKNOWN:
                return _UNKNOWN
            if a not in ("", None):
                return a
        return ""
    if name == "if":
        if len(args) < 3:
            return _UNKNOWN
        cond = _truthy(args[0])
        if cond is None:
            return _UNKNOWN
        return args[1] if cond else args[2]
    if name in ("int", "number"):
        n = _num(args[0]) if args else None
        if n is None:
            return _UNKNOWN
        return float(int(n)) if name == "int" else n
    if name == "round":
        n = _num(args[0]) if args else None
        digits = int(args[1]) if len(args) > 1 and isinstance(args[1], float) else 0
        return round(n, digits) if n is not None else _UNKNOWN
    return _UNKNOWN                       # honest "don't know"


def _coerce(value: Value) -> Value:
    """Runtime operand coercion: blank sentinel/None -> ``""``; ISO date ->
    ordinal float (so date relationals compare correctly)."""
    if value is EMPTY or value is None:
        return ""
    if isinstance(value, str) and _ISO_DATE.match(value):
        try:
            return float(_dt.date.fromisoformat(value).toordinal())
        except ValueError:
            return value
    return value


def _text(value: Value) -> str:
    if value in ("", _UNKNOWN, None) or value is EMPTY:
        return ""
    if isinstance(value, float):
        return format_value(value)
    return str(value)


def format_value(value: Value) -> str:
    """Human/string form of a computed value: integral floats lose the
    trailing ``.0``; blanks and unknowns render as ``""``."""
    if value in ("", None, _UNKNOWN) or value is EMPTY:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value)


# ---------------------------------------------------------------------------
# Parser (shared): evaluates during the parse, delegating ref/self/call to
# whichever resolver is supplied.
# ---------------------------------------------------------------------------
class _Parser:
    def __init__(self, tokens: List[tuple], resolver) -> None:
        self.tokens = tokens
        self.pos = 0
        self.resolver = resolver
        self.depth = 0

    def peek(self) -> tuple:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else ("eof", "")

    def next(self) -> tuple:
        tok = self.peek()
        self.pos += 1
        return tok

    def expect(self, kind: str) -> None:
        if self.next()[0] != kind:
            raise ValueError(f"expected {kind}")

    # grammar: or -> and -> comparison -> additive -> primary
    def parse_or(self) -> Value:
        left = self.parse_and()
        while self.peek() == ("word", "or"):
            self.next()
            left = _combine_or(left, self.parse_and())
        return left

    def parse_and(self) -> Value:
        left = self.parse_comparison()
        while self.peek() == ("word", "and"):
            self.next()
            left = _combine_and(left, self.parse_comparison())
        return left

    def parse_comparison(self) -> Value:
        left = self.parse_additive()
        kind, text = self.peek()
        if kind == "op" and text in ("=", "!=", "<", "<=", ">", ">="):
            self.next()
            return _compare(text, left, self.parse_additive())
        return left

    def parse_additive(self) -> Value:
        left = self.parse_primary()
        while True:
            kind, text = self.peek()
            if kind == "op" and text in ("+", "-", "*"):
                self.next()
                left = _arith(text, left, self.parse_primary())
            elif kind == "word" and text in ("div", "mod"):
                self.next()
                left = _arith(text, left, self.parse_primary())
            else:
                return left

    def parse_primary(self) -> Value:
        # parse_primary is the sole re-entry into the grammar (via a
        # parenthesised group, a unary minus, or a function call), so bounding
        # its depth here bounds the whole recursion - turning a stack-blowing
        # ``((((...))))`` into a clean ValueError the callers already handle.
        self.depth += 1
        if self.depth > _MAX_PARSE_DEPTH:
            raise ValueError("expression nesting too deep")
        try:
            return self._parse_primary()
        finally:
            self.depth -= 1

    def _parse_primary(self) -> Value:
        kind, text = self.next()
        if kind == "ref":
            return self.resolver.ref(text[2:-1])
        if kind == "number":
            return float(text)
        if kind == "string":
            return text[1:-1]
        if kind == "dot":
            return self.resolver.self_value()
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
            return _UNKNOWN              # bare word (unquoted literal etc.)
        raise ValueError(f"unexpected token {kind}:{text}")

    def _call(self, name: str) -> Value:
        self.expect("lpar")
        args: List[Value] = []
        if self.peek()[0] != "rpar":
            args.append(self.parse_or())
            while self.peek()[0] == "comma":
                self.next()
                args.append(self.parse_or())
        self.expect("rpar")
        return self.resolver.call(name, args)


def _combine_and(left: Value, right: Value) -> Tri:
    return _kleene_and(_truthy(left), _truthy(right))


def _combine_or(left: Value, right: Value) -> Tri:
    return _kleene_or(_truthy(left), _truthy(right))


def _parse(expression: str, resolver) -> Value:
    """Tokenize + evaluate, or raise ValueError/IndexError on bad input."""
    if len(expression) > _MAX_EXPR_LEN:
        raise ValueError("expression too long to evaluate safely")
    tokens = _tokenize(expression)
    parser = _Parser(tokens, resolver)
    result = parser.parse_or()
    if parser.peek()[0] != "eof":
        raise ValueError("trailing tokens")
    return result


# ---------------------------------------------------------------------------
# Public evaluators
# ---------------------------------------------------------------------------
class ExpressionEvaluator:
    """Static, tri-state evaluation over a partial assignment."""

    def evaluate(self, expression: str, values: Dict[str, Value]) -> Tri:
        """Evaluate *expression* under partial *values*.

        Returns ``True`` / ``False`` / ``None`` (unknown). ``None`` on any
        parse error too - unparseable expressions are the syntax
        validator's job, not this one's.
        """
        expression = (expression or "").strip()
        if not expression:
            return None
        try:
            return _truthy(_parse(expression, _StaticResolver(values)))
        except (ValueError, IndexError, RecursionError):
            return None


class RuntimeEvaluator:
    """Concrete evaluation for a live interview (every value is known)."""

    def evaluate(self, expression: str, values: Dict[str, Value],
                 self_value: Value = "") -> Value:
        """Return the concrete value of *expression* ("" when unknown)."""
        expression = (expression or "").strip()
        if not expression:
            return ""
        try:
            result = _parse(expression, _RuntimeResolver(values, self_value))
        except (ValueError, IndexError, RecursionError):
            return ""
        return "" if result is _UNKNOWN else result

    def truthy(self, expression: str, values: Dict[str, Value],
               self_value: Value = "", default: bool = True) -> bool:
        """Boolean value of *expression*; *default* when it can't be
        decided (an empty ``relevant`` means "always shown", and an
        expression we can't evaluate should not silently hide/block)."""
        expression = (expression or "").strip()
        if not expression:
            return default
        try:
            t = _truthy(_parse(expression, _RuntimeResolver(values, self_value)))
        except (ValueError, IndexError, RecursionError):
            return default
        return default if t is None else t

    def compute(self, expression: str, values: Dict[str, Value]) -> str:
        """Evaluate a ``calculation`` and return its display string."""
        return format_value(self.evaluate(expression, values))
