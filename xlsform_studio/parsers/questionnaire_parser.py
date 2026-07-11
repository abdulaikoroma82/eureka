"""Questionnaire text parser (Module 1 core).

Purpose
-------
Turn a flat list of text lines (as extracted from DOCX / PDF / plain text)
into a structured :class:`~xlsform_studio.models.Questionnaire` of
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
# Question numbering: "3.", "3)", "3:", "Q3.", "Q.3:", "Q3 " - the number is
# captured so logic like "if question 3 is yes" can reference it later.
_QUESTION_NUM = re.compile(r"^\s*(?:Q\s*\.?\s*)?(\d{1,3})\s*[\.\):]\s+", re.IGNORECASE)
_OPTION_BULLET = re.compile(
    r"^\s*(?:[-*•·o‣▪]|[☐❏□▢◻○◯]|\[\s*\]|\(\s*\)|[a-zA-Z][\.\)]|\d+[\.\)])\s+(.*)$")
# Coded answer options: "1 = Yes", "97 = Refused". Preserved as
# "code=Label" strings; the rule engine materialises the code as the choice
# name and the right-hand side as the label.
_CODED_OPTION = re.compile(r"^\s*([A-Za-z0-9_]{1,10})\s*=\s*(.{1,80})$")
# Required markers survey designers commonly use: a trailing asterisk or an
# explicit "(required)" tag on the question text.
_REQUIRED_MARK = re.compile(r"\s*(\*+|\(\s*required\s*\))\s*$", re.IGNORECASE)
_SECTION_KW = re.compile(r"^\s*(section|module|part|chapter)\b", re.IGNORECASE)
_INSTRUCTION_KW = re.compile(r"^\s*(instruction|note|enumerator|interviewer)\s*[:\-]", re.IGNORECASE)
_SKIP_KW = re.compile(r"^\s*\(?\s*if\b", re.IGNORECASE)
# A short line of 2-4 slash-separated options, e.g. "Yes / No" or
# "Low / Medium / High".  Each part must be a brief phrase (<=3 words).
_INLINE_SLASH = re.compile(
    r"^\s*([^/?]{1,30})(?:\s*/\s*([^/?]{1,30})){1,3}\s*$")
_TYPE_HINT = re.compile(r"\[(select_one|select_multiple|integer|decimal|text|date|"
                        r"time|datetime|geopoint|image|audio|video|barcode|calculate|note)"
                        r"(?:\s+[a-z0-9_]+)?\]", re.IGNORECASE)
_IMPERATIVE = re.compile(r"^\s*(record|take|enter|measure|note|indicate|scan|capture|"
                         r"write|specify|provide|give|read|collect|mark|photograph)\b",
                         re.IGNORECASE)
# Headings that introduce a roster / repeat block.
_REPEAT_HEADING = re.compile(r"\b(for\s+each|repeat\s+for|per\s+each)\b",
                             re.IGNORECASE)
# Internal forced-question sentinel emitted by upstream parsers (e.g. the
# DOCX grid flattener) to start a new question unambiguously.
_FORCED_QUESTION = re.compile(r"^\s*Q::\s*")


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
        current_section_type = "group"
        current: Optional[Question] = None

        for raw in lines:
            line = raw.strip()
            if not line:
                continue

            # 1. Section heading.  Headings phrased "FOR EACH ..." /
            #    "REPEAT FOR ..." start a repeat group (roster).
            if self._is_section(line):
                current_section = self._clean_section(line)
                current_section_type = ("repeat" if _REPEAT_HEADING.search(line)
                                        else "group")
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

            # 4. Bulleted / lettered option line.  A *numbered* marker is
            #    ambiguous ("2. No" vs "2. Respondent age") - disambiguate.
            opt = self._as_option(line)
            if opt is not None and current is not None and self._looks_like_option(opt, current):
                num = re.match(r"^\s*(\d+)[\.\)]\s+", line)
                if num and self._numbered_line_is_question(num.group(1), opt, current):
                    pass                       # fall through to question steps
                else:
                    if num:
                        current._numbered_opts = getattr(
                            current, "_numbered_opts", 0) + 1
                    # A bulleted "Male / Female" is two options.
                    if re.search(r"\s/\s", opt):
                        current.raw_choices.extend(
                            [p.strip() for p in opt.split("/") if p.strip()])
                    else:
                        current.raw_choices.append(opt)
                    continue

            # 5. Single-line slash-separated options, e.g. "Yes / No" or
            #    "Low / Medium / High".
            if current is not None and self._is_inline_options(line):
                current.raw_choices.extend(
                    [p.strip() for p in line.split("/") if p.strip()])
                continue

            # 5b. Coded answer options: "1 = Yes", "97 = Refused". Kept as
            #     "code=Label" so the code becomes the stored choice name.
            coded = _CODED_OPTION.match(line)
            if coded is not None and current is not None:
                current.raw_choices.append(
                    f"{coded.group(1)}={coded.group(2).strip()}")
                continue

            # 6. A new question.
            if self._is_question(line):
                current = self._new_question(line, current_section, current_section_type)
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
                current = self._new_question(line, current_section, current_section_type)
                qn.questions.append(current)

        return qn

    # ------------------------------------------------------------------
    def _new_question(self, line: str, section: str,
                      section_type: str = "group") -> Question:
        line = _FORCED_QUESTION.sub("", line)
        num_match = _QUESTION_NUM.match(line)
        label = _QUESTION_NUM.sub("", line).strip()

        # Required markers: a trailing asterisk or "(required)".
        required = False
        req = _REQUIRED_MARK.search(label)
        if req:
            required = True
            label = _REQUIRED_MARK.sub("", label).strip()

        q = Question(raw_label=label, section=section, section_type=section_type,
                     required=required,
                     source_number=num_match.group(1) if num_match else "")
        m = _TYPE_HINT.search(label)
        if m:
            q.xlsform_type = m.group(0).strip("[]").strip()
            q.raw_label = _TYPE_HINT.sub("", label).strip()
            q.label = q.raw_label
        return q

    def _is_section(self, line: str) -> bool:
        if _SECTION_KW.match(line):
            return True
        # Roster headings: "For each household member:", "REPEAT FOR EACH CHILD"
        if _REPEAT_HEADING.match(line.strip()) and not line.endswith("?"):
            return True
        letters = [c for c in line if c.isalpha()]
        if len(letters) >= 3 and all(c.isupper() for c in letters) and not line.endswith("?"):
            return True
        return False

    def _clean_section(self, line: str) -> str:
        cleaned = re.sub(r"^\s*(section|module|part|chapter)\b[\s:.\-]*", "", line,
                         flags=re.IGNORECASE).strip()
        # Strip roster phrasing: "For each household member:" -> "Household Member"
        cleaned = re.sub(r"^\s*(for\s+each|repeat\s+for(?:\s+each)?|per\s+each)\b[\s:,-]*",
                         "", cleaned, flags=re.IGNORECASE).strip().rstrip(":")
        # Strip a leading enumerator: "A:", "1.", "II)", etc.
        cleaned = re.sub(r"^[0-9A-Za-z]{1,3}[\.\):]\s*", "", cleaned).strip()
        return (cleaned or line).title() if cleaned.isupper() or cleaned == "" \
            else (cleaned.title() if cleaned.islower() else cleaned)

    def _is_question(self, line: str) -> bool:
        if _FORCED_QUESTION.match(line):
            return True
        if line.endswith("?"):
            return True
        if _QUESTION_NUM.match(line):
            return True
        if self._is_imperative(line):
            return True
        return False

    def _is_imperative(self, line: str) -> bool:
        """Detect data-collection prompts phrased as commands.

        e.g. "Record GPS location", "Take a photo", "Enter the total amount".
        """
        return bool(_IMPERATIVE.match(line))

    def _numbered_line_is_question(self, number: str, text: str,
                                   current: Question) -> bool:
        """Decide whether "N. text" under an open question is a new numbered
        question or a numbered answer option.

        Question signals win outright: a question mark, a topic keyword, or
        imperative phrasing. Otherwise a number that continues the option
        sequence ("1. Yes" then "2. No") is an option, and a number that
        continues the *question* sequence with a multi-word text is a
        question. Single non-topic words ("No") always stay options.
        """
        if text.endswith("?") or self._looks_like_topic(text) \
                or self._is_imperative(text):
            return True
        n = int(number)
        if n == getattr(current, "_numbered_opts", 0) + 1:
            return False
        last = current.source_number
        if last.isdigit() and n == int(last) + 1 and len(text.split()) >= 2:
            return True
        return False

    def _is_inline_options(self, line: str) -> bool:
        """True for a short line of 2-4 slash-separated answer options.

        e.g. "Yes / No", "Male / Female", "Low / Medium / High".  Guarded so
        prompts that merely contain a slash ("Record weight / height") are
        not swallowed: every part must be a brief phrase and the line must
        not read as a command or a new question topic.
        """
        if not _INLINE_SLASH.match(line) or "/" not in line:
            return False
        if self._is_imperative(line) or self._looks_like_topic(line):
            return False
        parts = [p.strip() for p in line.split("/")]
        if not (2 <= len(parts) <= 4):
            return False
        return all(p and len(p.split()) <= 3 for p in parts)

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
