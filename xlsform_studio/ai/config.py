"""AI feature configuration.

Purpose
-------
A single place describing which optional AI features are enabled for a run,
and the target languages for translation.  Kept separate from the core
:mod:`xlsform_studio.app.config` so the deterministic app config has zero
knowledge of AI - the two layers stay cleanly decoupled.

Inputs / outputs
-----------------
A plain dataclass, constructed by the CLI, the UI, or library callers.

Example
-------
>>> cfg = AIConfig(enabled=True, translate_languages=[("French", "fr")])
>>> cfg.any_feature_enabled
True
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

#: All AI sub-features, by key. Used to validate CLI/UI input.
#: The first group mutates the form (each change validated + logged); the
#: second group ("group", "rewrite", "order", "naming") is advisory-only -
#: it produces accept/reject suggestions and never changes the form itself.
AI_FEATURES = ("translate", "skip_logic", "domain_constraints",
              "cross_constraints", "classify", "review", "explain_findings",
              "narrative", "group", "rewrite", "order", "naming",
              "instructions", "completeness", "coverage", "indicators")

#: Accepted alternative spellings for feature keys (CLI convenience).
FEATURE_ALIASES = {
    "logic_fallback": "skip_logic",
    "explain": "explain_findings",
    "cross": "cross_constraints",
}


def normalize_features(features) -> list:
    """Map alias spellings onto canonical feature keys, preserving order."""
    out = []
    for f in features:
        canonical = FEATURE_ALIASES.get(f, f)
        if canonical not in out:
            out.append(canonical)
    return out


@dataclass
class AIConfig:
    """Which optional AI features to run, and with what settings."""

    enabled: bool = False
    features: List[str] = field(default_factory=lambda: list(AI_FEATURES))
    #: (language name, ISO 639-1 code) pairs, e.g. [("French", "fr")].
    translate_languages: List[Tuple[str, str]] = field(default_factory=list)
    #: Optional free-text description of the survey's domain and setting
    #: (e.g. "child nutrition survey in rural Sierra Leone"). Used by the
    #: domain-constraint and quality-review features to ground suggestions.
    survey_context: str = ""
    #: Where the translator caches finished translations between runs so a
    #: regenerated form doesn't re-pay for unchanged labels. Empty string
    #: disables caching.
    translation_cache_path: str = ".translation_cache.json"
    #: Study objectives / indicators / research questions, one per line.
    #: Used by the "coverage" feature to build the coverage matrix.
    objectives: str = ""

    @property
    def any_feature_enabled(self) -> bool:
        return self.enabled and bool(self.features)

    def wants(self, feature: str) -> bool:
        return self.enabled and feature in self.features

    @classmethod
    def disabled(cls) -> "AIConfig":
        return cls(enabled=False, features=[])
