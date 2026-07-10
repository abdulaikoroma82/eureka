"""AI translation (optional AI feature).

Purpose
-------
Generate XLSForm translation columns (``label::French (fr)``, etc.) from the
English labels the deterministic pipeline produced.  This is the one gap
identified in the capability review that is *inherently* unsolvable
deterministically - the tool can pass translations through if you supply
them, but it cannot invent them without a language model.

Design
------
One API call per target language, batching every label and choice label in
the form together, to keep cost and latency low regardless of form size.
The model is asked for a JSON object mapping a numeric key back to the
translation, so the response can be matched to source strings positionally
without relying on the model preserving exact source text.

Inputs
------
A compiled :class:`~xlsform_architect.models.Questionnaire` and a list of
``(language_name, language_code)`` pairs.

Outputs
-------
The questionnaire, mutated in place: ``label::<Language> (<code>)`` entries
are added to each question's and choice's ``extra`` dict (the exporter
already emits any such passthrough column dynamically).  Returns the list of
notes describing what was translated or why a language was skipped.

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
    """Generate translation columns for a questionnaire via DeepSeek."""

    def __init__(self, client: DeepSeekClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    def translate(self, questionnaire: Questionnaire,
                  languages: List[Tuple[str, str]]) -> List[str]:
        """Add ``label::<Language> (<code>)`` translations for each language."""
        notes: List[str] = []
        if not languages:
            return notes

        items, targets = self._collect_items(questionnaire)
        if not items:
            return notes

        for name, code in languages:
            column = f"label::{name} ({code})"
            try:
                translations = self._translate_batch(items, name)
            except AIError as exc:
                notes.append(f"[AI translation] Skipped {name}: {exc}")
                continue

            applied = 0
            for idx, target in enumerate(targets):
                value = translations.get(str(idx + 1))
                if value:
                    target.extra[column] = value
                    applied += 1
            notes.append(f"[AI translation] Added {applied}/{len(items)} "
                        f"labels in {name} ({code}).")
        return notes

    # ------------------------------------------------------------------
    def _collect_items(self, qn: Questionnaire):
        """Flatten every translatable label into a positional list.

        Returns (texts, targets) where targets[i] is the Question or Choice
        object whose ``extra`` dict should receive texts[i]'s translation.
        """
        texts: List[str] = []
        targets = []
        for q in qn.questions:
            if q.is_structural:
                continue
            label = (q.label or q.raw_label or "").strip()
            if label:
                texts.append(label)
                targets.append(q)
        for cl in qn.choice_lists.values():
            for choice in cl.choices:
                if choice.label:
                    texts.append(choice.label)
                    targets.append(choice)
        return texts, targets

    def _translate_batch(self, items: List[str], language_name: str) -> dict:
        numbered = "\n".join(f"{i + 1}. {text}" for i, text in enumerate(items))
        user_prompt = (
            f"Translate the following {len(items)} questionnaire labels into "
            f"{language_name}. Return a json object as instructed.\n\n{numbered}")
        return self.client.complete_json(_SYSTEM_PROMPT, user_prompt,
                                         max_tokens=max(1000, len(items) * 60))
