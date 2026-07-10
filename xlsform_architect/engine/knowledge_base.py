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
    """In-memory view of the standard XLSForm rule pack."""

    xlsform_rules: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, directory: Optional[Path] = None,
             rules_file: str = "xlsform_rules.yaml") -> "KnowledgeBase":
        """Load the rule pack from *directory* (defaults to the bundled one).

        Pass a different *rules_file* to use a customised ruleset that follows
        the same structure as ``xlsform_rules.yaml``.
        """
        directory = directory or KNOWLEDGE_DIR
        return cls(xlsform_rules=_read_yaml(directory / rules_file))

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
