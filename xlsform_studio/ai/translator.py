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

A local **translation cache** (``.translation_cache.json``, timestamped
entries keyed by language + source text) sits in front of the API: a label
translated in a previous run is served from disk, so regenerating a form -
the everyday workflow - costs nothing for text that hasn't changed, and the
API is called only for genuinely new labels. Cached use is logged in the
notes. The cache is best-effort: any read/write problem is ignored and the
feature falls back to plain API calls (fail-open, like everything in this
layer). Pass ``cache_path=None`` to disable it.

Inputs
------
A compiled :class:`~xlsform_studio.models.Questionnaire` and a list of
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
>>> from xlsform_studio.models import Questionnaire, Question
>>> qn = Questionnaire(questions=[Question(name="age", label="Age", xlsform_type="integer")])
>>> AITranslator(client=None).translate(qn, [("French", "fr")])  # doctest: +SKIP
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from ..models import Questionnaire
from .client import AIError, DeepSeekClient

#: Default on-disk cache location (current working directory).
DEFAULT_CACHE_PATH = Path(".translation_cache.json")

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

    def __init__(self, client: DeepSeekClient,
                 cache_path: Optional[Union[str, Path]] = None) -> None:
        self.client = client
        #: None disables caching (the default for direct construction, so
        #: creating a translator never touches the filesystem by surprise);
        #: the AI pipeline passes the path configured on AIConfig.
        self.cache_path = Path(cache_path) if cache_path else None

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

        cache = self._load_cache()
        cache_dirty = False

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

            # Serve previously-translated labels from the cache first.
            cached_count = 0
            uncached = []
            for text, target in missing:
                hit = cache.get(self._cache_key(code, text))
                if hit and hit.get("translation"):
                    target.extra[column] = hit["translation"]
                    cached_count += 1
                else:
                    uncached.append((text, target))
            if cached_count:
                notes.append(f"[AI translation] {name} ({code}): "
                            f"{cached_count} label(s) served from the local "
                            f"translation cache (no API cost).")
            if not uncached:
                continue

            items = [text for text, _ in uncached]
            try:
                translations = self._translate_batch(items, name)
            except AIError as exc:
                notes.append(f"[AI translation] Skipped {name}: {exc}")
                continue

            applied = 0
            stamp = _dt.datetime.now().isoformat(timespec="seconds")
            for idx, (text, target) in enumerate(uncached):
                value = translations.get(str(idx + 1))
                if value:
                    target.extra[column] = value
                    cache[self._cache_key(code, text)] = {
                        "translation": value, "timestamp": stamp}
                    cache_dirty = True
                    applied += 1

            kept_note = (f" ({already} already supplied and left as-is)"
                        if already else "")
            notes.append(f"[AI translation] Added {applied}/{len(uncached)} "
                        f"missing label(s) in {name} ({code}){kept_note}.")

        if cache_dirty:
            self._save_cache(cache)
        return notes

    # ------------------------------------------------------------------
    # Cache (best-effort; every failure falls back to plain API calls)
    # ------------------------------------------------------------------
    @staticmethod
    def _cache_key(code: str, text: str) -> str:
        return f"{code}␟{text}"        # unit separator; safe in JSON keys

    def _load_cache(self) -> Dict[str, dict]:
        if self.cache_path is None:
            return {}
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_cache(self, cache: Dict[str, dict]) -> None:
        if self.cache_path is None:
            return
        try:
            self.cache_path.write_text(
                json.dumps(cache, ensure_ascii=False, indent=1),
                encoding="utf-8")
        except OSError:
            pass                              # cache is an optimisation only

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
