"""Application configuration.

Purpose
-------
Central, dependency-free place for paths, constants and runtime options.
No other module should hard-code a directory or a magic string that belongs
here.

Inputs / outputs
----------------
Exposes module-level constants and a small :class:`Settings` dataclass whose
defaults can be overridden by environment variables (prefixed ``XLSFA_``).

Example
-------
>>> from xlsform_architect.app.config import CONFIG
>>> CONFIG.output_dir.name
'output'
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

# --- project locations -----------------------------------------------------
PACKAGE_ROOT: Path = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR: Path = PACKAGE_ROOT / "knowledge"
TEMPLATES_DIR: Path = PACKAGE_ROOT / "templates"
DEFAULT_OUTPUT_DIR: Path = PACKAGE_ROOT / "output"
EXAMPLES_DIR: Path = PACKAGE_ROOT / "examples"

# --- supported deployment targets -----------------------------------------
DEPLOYMENT_TARGETS: List[str] = ["kobo", "surveycto", "odk"]

# --- supported input formats ----------------------------------------------
SUPPORTED_INPUT_EXTENSIONS: List[str] = [".json", ".csv", ".xlsx", ".xls",
                                         ".docx", ".pdf", ".txt", ".md"]

# --- XLSForm sheet definitions --------------------------------------------
SURVEY_COLUMNS: List[str] = [
    "type", "name", "label", "hint", "required",
    "relevant", "constraint", "constraint_message", "calculation",
    "appearance", "default",
]
CHOICES_COLUMNS: List[str] = ["list_name", "name", "label"]
SETTINGS_COLUMNS: List[str] = ["form_title", "form_id", "version", "default_language", "style"]

# Names of the well-known reusable choice lists.
YES_NO_LIST: str = "yes_no"


def _env(name: str, default: str) -> str:
    return os.environ.get(f"XLSFA_{name}", default)


@dataclass
class Settings:
    """Runtime settings, overridable through ``XLSFA_*`` environment vars."""

    output_dir: Path = field(default_factory=lambda: Path(_env("OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR))))
    default_target: str = field(default_factory=lambda: _env("DEFAULT_TARGET", "kobo"))
    default_version_format: str = "%Y%m%d%H%M"
    #: When True, unknown / ambiguous questions still produce a note row
    #: rather than being dropped, so nothing is silently lost.
    keep_unresolved_as_note: bool = True

    def ensure_output_dir(self) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir


CONFIG = Settings()
