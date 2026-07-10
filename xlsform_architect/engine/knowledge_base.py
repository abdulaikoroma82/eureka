"""Knowledge base loader (Module 8).

Purpose
-------
Load and cache the YAML rule packs from ``knowledge/`` so the rest of the
engine can query them.  New rules are added by editing the YAML files - no
Python change required, satisfying the "configurable rule files" requirement.

Inputs
------
YAML files in :data:`xlsform_architect.app.config.KNOWLEDGE_DIR`.

Outputs
-------
A :class:`KnowledgeBase` exposing parsed dictionaries plus convenience
accessors (constraint templates, yes/no config, category choice lists...).

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
    """In-memory view of all knowledge packs."""

    xlsform_rules: Dict[str, Any] = field(default_factory=dict)
    nutrition_rules: Dict[str, Any] = field(default_factory=dict)
    imam_rules: Dict[str, Any] = field(default_factory=dict)
    mms_rules: Dict[str, Any] = field(default_factory=dict)
    dhis2_dictionary: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, directory: Optional[Path] = None) -> "KnowledgeBase":
        """Load every known pack from *directory* (defaults to the bundled one)."""
        directory = directory or KNOWLEDGE_DIR
        return cls(
            xlsform_rules=_read_yaml(directory / "xlsform_rules.yaml"),
            nutrition_rules=_read_yaml(directory / "nutrition_rules.yaml"),
            imam_rules=_read_yaml(directory / "imam_rules.yaml"),
            mms_rules=_read_yaml(directory / "mms_rules.yaml"),
            dhis2_dictionary=_read_yaml(directory / "dhis2_dictionary.yaml"),
        )

    # -- xlsform_rules accessors ---------------------------------------
    def type_keywords(self) -> List[Dict[str, Any]]:
        return self.xlsform_rules.get("type_keywords", [])

    def yes_no(self) -> Dict[str, Any]:
        return self.xlsform_rules.get("yes_no", {})

    def constraint_templates(self) -> List[Dict[str, Any]]:
        return self.xlsform_rules.get("constraints", [])

    def type_constraints(self) -> Dict[str, Any]:
        return self.xlsform_rules.get("type_constraints", {})

    def logic_tokens(self) -> Dict[str, List[str]]:
        return self.xlsform_rules.get("logic_tokens", {})

    def naming_rules(self) -> Dict[str, Any]:
        return self.xlsform_rules.get("naming", {})

    # -- category choice-list packs ------------------------------------
    def category_choice_lists(self, category: str) -> Dict[str, List[Dict[str, str]]]:
        """Return predefined choice lists for a survey *category*.

        Merges the general nutrition lists with the category-specific pack so
        that e.g. an IMAM survey gets both ``sex`` and ``admission_type``.
        """
        lists: Dict[str, List[Dict[str, str]]] = {}
        lists.update(self.nutrition_rules.get("choice_lists", {}) or {})

        if category == "imam":
            lists.update(self.imam_rules.get("choice_lists", {}) or {})
        elif category in ("mms", "anc"):
            lists.update((self.mms_rules.get("mms", {}) or {}).get("choice_lists", {}) or {})
        elif category == "vas_d":
            lists.update((self.mms_rules.get("vas_d", {}) or {}).get("choice_lists", {}) or {})
        return lists

    def dhis2_element(self, variable_name: str) -> Optional[Dict[str, Any]]:
        return (self.dhis2_dictionary.get("data_elements", {}) or {}).get(variable_name)
