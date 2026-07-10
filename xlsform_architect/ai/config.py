"""AI feature configuration.

Purpose
-------
A single place describing which optional AI features are enabled for a run,
and the target languages for translation.  Kept separate from the core
:mod:`xlsform_architect.app.config` so the deterministic app config has zero
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
AI_FEATURES = ("translate", "skip_logic", "cross_constraints", "classify",
              "review", "explain_findings")


@dataclass
class AIConfig:
    """Which optional AI features to run, and with what settings."""

    enabled: bool = False
    features: List[str] = field(default_factory=lambda: list(AI_FEATURES))
    #: (language name, ISO 639-1 code) pairs, e.g. [("French", "fr")].
    translate_languages: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def any_feature_enabled(self) -> bool:
        return self.enabled and bool(self.features)

    def wants(self, feature: str) -> bool:
        return self.enabled and feature in self.features

    @classmethod
    def disabled(cls) -> "AIConfig":
        return cls(enabled=False, features=[])
