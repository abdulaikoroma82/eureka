"""Questionnaire text parser (Module 1 core).

Purpose
-------
Turn a flat list of text lines (as extracted from DOCX / PDF / plain text)
into a structured :class:`~xlsform_architect.models.Questionnaire` of
questions, options, sections and inline skip logic - deterministically, with
no AI.

Heuristics
----------
* SECTION HEADINGS: ALL-CAPS lines, or lines starting with "Section",
  "Module", "Part".
* QUESTIONS: lines ending in "?" or starting with a number ("1.", "Q1)").
* OPTIONS: short lines under a question, optionally bulleted / lettered
  ("- Yes", "a) No", "[ ] Male"), or a single "Yes / No" line.
* INSTRUCTIONS / SKIP LOGIC: lines beginning with "If ", "Instruction:",
  "Note:", or parenthetical "(if yes ...)" are attached to the current
  question's ``logic`` / ``instruction``.

Inputs
------
``list[str]`` of lines (``parse_lines``) or raw text (``parse_text``).

Outputs
-------
A :class:`Questionnaire` (raw, not yet compiled by the engine).

Example
-------
>>> text = '''Is the child currently enrolled in OTP?
... Yes
... No
... If yes, record admission date.'''
>>> qn = QuestionnaireParser().parse_text(text)
>>> qn.questions[0].raw_choices
['Yes', 'No']
>>> qn.questions[0].logic
'If yes, record admission date.'
"""

from __future__ import annotations

import re
from typing import List, Optional

from ..models import Question, Questionnaire

# --- line classification patterns ------------------------------------------
_QUESTION_NUM = re.compile(r"^\s*(?:Q\s*)?\d+[\.\)]\s+", re.IGNORECASE)
_OPTION_BULLET = re.compile(r"^\s*(?:[-*•·o]|\[\s*\]|\(\s*\)|[a-zA-Z][\.\)]|\d+[\.\)])\s+(.*)$")
_SECTION_KW = re.compile(r"^\s*(section|module|part|chapter)\b", re.IGNORECASE)
_INSTRUCTION_KW = re.compile(r"^\s*(instruction|note|enumerator|interviewer)\s*[:\-]", re.IGNORECASE)
_SKIP_KW = re.compile(r"^\s*\(?\s*if\b", re.IGNORECASE)
_INLINE_SLASH = re.compile(r"^\s*(yes\s*/\s*no|male\s*/\s*female)\s*$", re.IGNORECASE)
_TYPE_HINT = re.compile(r"\[(select_one|select_multiple|integer|decimal|text|date|"
                        r"time|datetime|geopoint|image|audio|video|barcode|calculate|note)"
                        r"(?:\s+[a-z0-9_]+)?\]", re.IGNORECASE)
_IMPERATIVE = re.compile(r"^\s*(record|take|enter|measure|note|indicate|scan|capture|"
                         r"write|specify|provide|give|read|collect|mark|photograph)\b",
                         re.IGNORECASE)


class QuestionnaireParser:
    """Deterministic text-to-structure parser."""

    #: Extra topic words (beyond the knowledge-base type keywords) that mark a
    #: line as a *new question* rather than a stacked answer option.
    _EXTRA_TOPICS = {"name", "sex", "gender", "number", "date", "location",
                     "household", "facility", "id"}

    def __init__(self, knowledge=None) -> None:
        # Reuse the engine's type keywords so the parser and classifier agree
        # on what looks like a question topic.  Kept optional/lazy so the
        # parser has no hard dependency at import time.
        topics = set(self._EXTRA_TOPICS)
        try:
            from ..engine.knowledge_base import KnowledgeBase
            kb = knowledge or KnowledgeBase.load()
            for rule in kb.type_keywords():
                for kw in rule.get("keywords", []):
                    kw = kw.strip().lower()
                    if kw and kw.isalpha():
                        topics.add(kw)
        except Exception:  # pragma: no cover - parser still works without kb
            pass
        self._topic_keywords = topics

    def parse_text(self, text: str) -> Questionnaire:
        return self.parse_lines(text.splitlines())

    # ------------------------------------------------------------------
    def parse_lines(self, lines: List[str]) -> Questionnaire:
        qn = Questionnaire()
        current_section = ""
        current: Optional[Question] = None

        for raw in lines:
            line = raw.strip()
            if not line:
                continue

            # 1. Section heading.
            if self._is_section(line):
                current_section = self._clean_section(line)
                current = None
                continue

            # 2. Instruction / note line -> attach to current question.
            if _INSTRUCTION_KW.match(line):
                if current is not None:
                    current.instruction = self._strip_prefix(line)
                continue

            # 3. Skip / relevance logic line.
            if _SKIP_KW.match(line):
                if current is not None:
                    current.logic = (current.logic + " " + line).strip() if current.logic else line
                continue

            # 4. "Yes / No" single-line options.
            if _INLINE_SLASH.match(line) and current is not None:
                current.raw_choices.extend([p.strip() for p in re.split(r"/", line)])
                continue

            # 5. Bulleted / lettered option line.
            opt = self._as_option(line)
            if opt is not None and current is not None and self._looks_like_option(opt, current):
                # A bulleted "Male / Female" is two options.
                if re.search(r"\s/\s", opt):
                    current.raw_choices.extend([p.strip() for p in opt.split("/") if p.strip()])
                else:
                    current.raw_choices.append(opt)
                continue

            # 6. A new question.
            if self._is_question(line):
                current = self._new_question(line, current_section)
                qn.questions.append(current)
                continue

            # 7. Continuation / unbulleted option under an open question:
            #    short, option-like lines (e.g. stacked "Yes" / "No") are
            #    collected as answer options.  A short line that names a new
            #    topic (contains a type keyword) starts a new question instead.
            if current is not None and len(line) <= 60 and self._short_wordset(line) \
                    and not self._is_imperative(line) and not self._looks_like_topic(line):
                current.raw_choices.append(line)
            else:
                # Otherwise treat as a standalone prompt / statement question
                # so nothing in the source document is silently dropped.
                current = self._new_question(line, current_section)
                qn.questions.append(current)

        return qn

    # ------------------------------------------------------------------
    def _new_question(self, line: str, section: str) -> Question:
        label = _QUESTION_NUM.sub("", line).strip()
        q = Question(raw_label=label, section=section)
        m = _TYPE_HINT.search(label)
        if m:
            q.xlsform_type = m.group(0).strip("[]").strip()
            q.raw_label = _TYPE_HINT.sub("", label).strip()
            q.label = q.raw_label
        return q

    def _is_section(self, line: str) -> bool:
        if _SECTION_KW.match(line):
            return True
        letters = [c for c in line if c.isalpha()]
        if len(letters) >= 3 and all(c.isupper() for c in letters) and not line.endswith("?"):
            return True
        return False

    def _clean_section(self, line: str) -> str:
        cleaned = re.sub(r"^\s*(section|module|part|chapter)\b[\s:.\-]*", "", line,
                         flags=re.IGNORECASE).strip()
        # Strip a leading enumerator: "A:", "1.", "II)", etc.
        cleaned = re.sub(r"^[0-9A-Za-z]{1,3}[\.\):]\s*", "", cleaned).strip()
        return (cleaned or line).title() if cleaned.isupper() or cleaned == "" else cleaned

    def _is_question(self, line: str) -> bool:
        if line.endswith("?"):
            return True
        if _QUESTION_NUM.match(line):
            return True
        if self._is_imperative(line):
            return True
        return False

    def _is_imperative(self, line: str) -> bool:
        """Detect data-collection prompts phrased as commands.

        e.g. "Record GPS location", "Take a photo", "Measure the MUAC".
        """
        return bool(_IMPERATIVE.match(line))

    def _looks_like_topic(self, line: str) -> bool:
        """True if the line names a new question topic (has a type keyword).

        Used to stop a stacked-option run when a new short question appears,
        e.g. "Child age in months" after a Yes/No block.
        """
        low = line.lower()
        for kw in self._topic_keywords:
            if len(kw) <= 4:
                if re.search(rf"\b{re.escape(kw)}\b", low):
                    return True
            elif kw in low:
                return True
        return False

    def _as_option(self, line: str) -> Optional[str]:
        m = _OPTION_BULLET.match(line)
        if m:
            return m.group(1).strip()
        return None

    def _looks_like_option(self, text: str, current: Question) -> bool:
        # Options are generally short and not themselves questions.
        return not text.endswith("?") and len(text) <= 80

    def _short_wordset(self, line: str) -> bool:
        # A plausible bare option: few words, no sentence punctuation.
        return len(line.split()) <= 5 and not line.endswith(".")

    @staticmethod
    def _strip_prefix(line: str) -> str:
        return re.sub(r"^\s*\w+\s*[:\-]\s*", "", line).strip()
