"""Structured logging for observability and audit (cross-cutting).

Purpose
-------
Give every run a traceable record of what happened without changing any
behaviour: which AI features ran or were skipped and why, every network
call's outcome, and every AI suggestion's accept/apply/reject decision.
This is separate from the assumption log (which is form-content-facing and
ships inside the output package) - this is operator-facing, for debugging
a run or auditing AI activity after the fact.

Design
------
Two stdlib loggers under fixed names:

* ``xlsform_studio`` - general run tracing (feature start/skip, timings,
  errors). Use :func:`get_logger` for a per-module child logger.
* ``xlsform_studio.audit`` - one line per AI-suggested change: proposed,
  accepted, applied, or rejected. Use :func:`get_audit_logger`.

Both are silent by default (a :class:`~logging.NullHandler` is attached at
import time, per Python library convention) so importing the package never
prints anything. Call :func:`configure_logging` once, from an entry point
(the CLI, the UI), to attach a console handler.

Security note
-------------
Never pass secrets (API keys, full prompt/response bodies) to these
loggers. Log shapes and outcomes (counts, durations, error *messages*),
not payloads - see :mod:`xlsform_studio.ai.client`, which logs prompt
length rather than prompt content for exactly this reason.

Example
-------
>>> configure_logging(level="DEBUG")
>>> log = get_logger("demo")
>>> log.info("hello")  # doctest: +SKIP
"""

from __future__ import annotations

import logging
import sys

_ROOT_NAME = "xlsform_studio"
_AUDIT_NAME = "xlsform_studio.audit"

logging.getLogger(_ROOT_NAME).addHandler(logging.NullHandler())

_configured = False


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the ``xlsform_studio`` namespace."""
    return logging.getLogger(f"{_ROOT_NAME}.{name}")


def get_audit_logger() -> logging.Logger:
    """Return the dedicated audit-trail logger for AI suggestion outcomes."""
    return logging.getLogger(_AUDIT_NAME)


def configure_logging(level: str = "INFO", stream=None) -> None:
    """Attach a console handler to the package logger (idempotent).

    Safe to call more than once (e.g. once from the CLI, once from a
    library caller) - later calls only adjust the level, they never stack
    duplicate handlers.
    """
    global _configured
    root = logging.getLogger(_ROOT_NAME)
    resolved = getattr(logging, level.upper(), logging.INFO)
    root.setLevel(resolved)
    if _configured:
        return
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))
    root.addHandler(handler)
    root.propagate = False
    _configured = True
