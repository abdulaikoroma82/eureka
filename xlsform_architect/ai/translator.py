"""AI translation (optional AI feature).

Purpose
-------
Generate XLSForm translation columns (``label::French (fr)``, etc.) from the
English labels the deterministic pipeline produced.  This is the one gap
identified in the capability review that is *inherently* unsolvable
deterministically - the tool can pass translations through if you supply
them, but it cannot invent them without a language model.

This is a genuine co-share, not a pure AI takeover: **any translation you
already supplied (via JSON, the design grid, or an imported XLSForm's
``label::<Language>`` columns) is authoritative and is never touched.** AI
only fills in the labels you did *not* already translate, per language. A
question you fully translated yourself costs nothing to skip; a form where
you covered half the labels only pays for the other half.

Design
------
One API call per target language, batching only the *missing* labels and
choice labels for that language, so cost and latency track what's actually
needed rather than the form's total size. If nothing is missing for a
language, no call is made at all. The model is asked for a JSON object
mapping a numeric key back to the translation, so the response can be
matched to source strings positionally without relying on the model
preserving exact source text.

Inputs
------
A compiled :class:`~xlsform_architect.models.Questionnaire` and a list of
``(language_name, language_code)`` pairs.

Outputs
-------
The questionnaire, mutated in place: ``label::<Language> (<code>)`` entries
are added to each question's and choice's ``extra`` dict ONLY where that key
was not already present (the exporter already emits any such passthrough
column dynamically). Returns the list of notes describing what was
translated, what was left as-is because you supplied it, or why a language
was skipped.

Example
-------
>>> from xlsform_architect.models import Questionnaire, Question
>>> qn = Questionnaire(questions=[Question(name="age", label="Age", xlsform_type="integer")])
>>> AITranslator(client=None).translate(qn, [("French", "fr")])  # doctest: +SKIP
"""

from __future__ import annotations

from typing import List, Tuple

from ..models import Questionnaire
from .client import AIError, DeepSeekClient

_SYSTEM_PROMPT = (
    "You are a professional survey translator. Translate short questionnaire "
    "field labels accurately and concisely, preserving meaning and register. "
    "Do not translate placeholders like ${variable_name}; keep them verbatim. "
    "Respond ONLY with a json object mapping each numeric key (as a string) "
    "to its translation, e.g. {\"1\": \"...\", \"2\": \"...\"}. "
    "Provide a translation for every key you are given, in the same order.")


class AITranslator:
    """Generate translation columns for a questionnaire via DeepSeek.

    Never overwrites a translation already present - only fills gaps.
    """

    def __init__(self, client: DeepSeekClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    def translate(self, questionnaire: Questionnaire,
                  languages: List[Tuple[str, str]]) -> List[str]:
        """Fill in missing ``label::<Language> (<code>)`` translations."""
        notes: List[str] = []
        if not languages:
            return notes

        all_targets = self._collect_targets(questionnaire)
        if not all_targets:
            return notes

        for name, code in languages:
            column = f"label::{name} ({code})"
            missing = [(text, target) for text, target in all_targets
                      if column not in target.extra]
            already = len(all_targets) - len(missing)

            if not missing:
                notes.append(f"[AI translation] {name} ({code}): all "
                            f"{len(all_targets)} label(s) already supplied; "
                            f"nothing to do.")
                continue

            items = [text for text, _ in missing]
            try:
                translations = self._translate_batch(items, name)
            except AIError as exc:
                notes.append(f"[AI translation] Skipped {name}: {exc}")
                continue

            applied = 0
            for idx, (_, target) in enumerate(missing):
                value = translations.get(str(idx + 1))
                if value:
                    target.extra[column] = value
                    applied += 1

            kept_note = (f" ({already} already supplied and left as-is)"
                        if already else "")
            notes.append(f"[AI translation] Added {applied}/{len(missing)} "
                        f"missing label(s) in {name} ({code}){kept_note}.")
        return notes

    # ------------------------------------------------------------------
    def _collect_targets(self, qn: Questionnaire):
        """Flatten every translatable label into a (text, target) list.

        ``target`` is the Question or Choice object whose ``extra`` dict
        should receive the translation.
        """
        out = []
        for q in qn.questions:
            if q.is_structural:
                continue
            label = (q.label or q.raw_label or "").strip()
            if label:
                out.append((label, q))
        for cl in qn.choice_lists.values():
            for choice in cl.choices:
                if choice.label:
                    out.append((choice.label, choice))
        return out

    def _translate_batch(self, items: List[str], language_name: str) -> dict:
        numbered = "\n".join(f"{i + 1}. {text}" for i, text in enumerate(items))
        user_prompt = (
            f"Translate the following {len(items)} questionnaire labels into "
            f"{language_name}. Return a json object as instructed.\n\n{numbered}")
        return self.client.complete_json(_SYSTEM_PROMPT, user_prompt,
                                         max_tokens=max(1000, len(items) * 60))
