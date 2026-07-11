"""Knowledge base loader (Module 8).

Purpose
-------
Load and cache the standard XLSForm rule pack from ``knowledge/`` so the rest
of the engine can query it.  New or customised rules are added by editing the
YAML file - no Python change required, satisfying the "configurable rule
files" requirement.

The bundled ruleset is domain-neutral: it encodes standard XLSForm behaviour
that applies to any questionnaire.  To specialise the tool for a particular
programme, point it at a custom rules file with the same structure.

Inputs
------
YAML file(s) in :data:`xlsform_architect.app.config.KNOWLEDGE_DIR`.

Outputs
-------
A :class:`KnowledgeBase` exposing parsed dictionaries plus convenience
accessors (constraint templates, yes/no config, calculation expressions...).

Example
-------
>>> kb = KnowledgeBase.load()
>>> kb.yes_no()["list_name"]
'yes_no'
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from ..app.config import KNOWLEDGE_DIR


def _read_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


@dataclass
class KnowledgeBase:
    """In-memory view of the standard XLSForm rule pack and platform profiles."""

    xlsform_rules: Dict[str, Any] = field(default_factory=dict)
    platforms: Dict[str, Any] = field(default_factory=dict)

    #: Names of the domain packs merged into this knowledge base.
    packs: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, directory: Optional[Path] = None,
             rules_file: str = "xlsform_rules.yaml",
             packs: Optional[List[str]] = None) -> "KnowledgeBase":
        """Load the rule pack from *directory* (defaults to the bundled one).

        Pass a different *rules_file* to use a customised ruleset that follows
        the same structure as ``xlsform_rules.yaml``.  Platform profiles are
        always read from ``platforms.yaml`` in the same directory (falling
        back to the bundled one so custom rule dirs need not duplicate it).

        *packs* names optional **domain rule packs** (Module D7) from the
        ``packs/`` subdirectory — e.g. ``packs=["nutrition"]`` merges
        ``knowledge/packs/nutrition.yaml`` on top of the neutral rules.
        Pack entries take precedence: their ordered rules (type keywords,
        constraint templates) are matched *before* the neutral ones, and
        their scalar sections shallow-override. With no packs, behaviour
        is byte-for-byte identical to the neutral ruleset.
        """
        directory = directory or KNOWLEDGE_DIR
        platform_data = _read_yaml(directory / "platforms.yaml")
        if not platform_data and directory != KNOWLEDGE_DIR:
            platform_data = _read_yaml(KNOWLEDGE_DIR / "platforms.yaml")
        rules = _read_yaml(directory / rules_file)
        loaded: List[str] = []
        for name in packs or []:
            pack_path = directory / "packs" / f"{name}.yaml"
            if not pack_path.exists() and directory != KNOWLEDGE_DIR:
                pack_path = KNOWLEDGE_DIR / "packs" / f"{name}.yaml"
            pack = _read_yaml(pack_path)
            if not pack:
                raise FileNotFoundError(
                    f"Unknown domain rule pack '{name}' (looked for "
                    f"{pack_path}). Available: "
                    f"{', '.join(cls.available_packs(directory)) or 'none'}")
            rules = cls._merge_pack(rules, pack)
            loaded.append(name)
        return cls(xlsform_rules=rules,
                   platforms=platform_data.get("platforms", {}),
                   packs=loaded)

    @staticmethod
    def available_packs(directory: Optional[Path] = None) -> List[str]:
        """Names of the domain rule packs shipped in ``knowledge/packs/``."""
        directory = directory or KNOWLEDGE_DIR
        packs_dir = directory / "packs"
        if not packs_dir.is_dir() and directory != KNOWLEDGE_DIR:
            packs_dir = KNOWLEDGE_DIR / "packs"
        if not packs_dir.is_dir():
            return []
        return sorted(p.stem for p in packs_dir.glob("*.yaml"))

    @staticmethod
    def _merge_pack(rules: Dict[str, Any], pack: Dict[str, Any]) -> Dict[str, Any]:
        """Merge a domain pack on top of *rules*, pack entries winning.

        Ordered, first-match-wins lists (``type_keywords``, ``constraints``)
        get the pack's entries PREPENDED so domain rules match before
        neutral ones. Dict sections shallow-merge with the pack's keys
        overriding. Anything else the pack defines replaces the section.
        """
        merged = dict(rules)
        for key, value in pack.items():
            if key in ("type_keywords", "constraints"):
                merged[key] = list(value or []) + list(merged.get(key, []))
            elif isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
        return merged

    # -- platform accessors ---------------------------------------------
    def platform(self, target: str) -> Dict[str, Any]:
        """Return the profile for *target* (kobo/surveycto/odk), or {}."""
        return self.platforms.get((target or "").lower(), {})

    def platform_names(self) -> List[str]:
        return list(self.platforms.keys())

    # -- xlsform_rules accessors ---------------------------------------
    def type_keywords(self) -> List[Dict[str, Any]]:
        return self.xlsform_rules.get("type_keywords", [])

    def yes_no(self) -> Dict[str, Any]:
        return self.xlsform_rules.get("yes_no", {})

    def constraint_templates(self) -> List[Dict[str, Any]]:
        return self.xlsform_rules.get("constraints", [])

    def type_constraints(self) -> Dict[str, Any]:
        return self.xlsform_rules.get("type_constraints", {})

    def calculations(self) -> Dict[str, str]:
        return self.xlsform_rules.get("calculations", {})

    def logic_tokens(self) -> Dict[str, List[str]]:
        return self.xlsform_rules.get("logic_tokens", {})

    def naming_rules(self) -> Dict[str, Any]:
        return self.xlsform_rules.get("naming", {})
