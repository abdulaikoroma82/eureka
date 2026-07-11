"""Application configuration.

Purpose
-------
Central, dependency-free place for paths, constants and runtime options.
No other module should hard-code a directory or a magic string that belongs
here.

Inputs / outputs
----------------
Exposes module-level constants and a small :class:`Settings` dataclass whose
defaults can be overridden by environment variables (prefixed ``XLSFS_``).

Example
-------
>>> from xlsform_studio.app.config import CONFIG
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
DEFAULT_OUTPUT_DIR: Path = PACKAGE_ROOT / "output"
EXAMPLES_DIR: Path = PACKAGE_ROOT / "examples"

# --- supported deployment targets -----------------------------------------
# Fallback list; the authoritative set is knowledge/platforms.yaml (loaded via
# KnowledgeBase.platform_names()), so adding a platform is a YAML-only change.
DEPLOYMENT_TARGETS: List[str] = ["kobo", "surveycto", "odk", "ona", "commcare"]

# --- supported input formats ----------------------------------------------
SUPPORTED_INPUT_EXTENSIONS: List[str] = [".json", ".csv", ".xlsx", ".xls",
                                         ".docx", ".pdf", ".txt", ".md"]

# --- XLSForm sheet definitions --------------------------------------------
SURVEY_COLUMNS: List[str] = [
    "type", "name", "label", "hint", "required",
    "relevant", "constraint", "constraint_message", "calculation",
    "choice_filter", "appearance", "default",
]
CHOICES_COLUMNS: List[str] = ["list_name", "name", "label"]
SETTINGS_COLUMNS: List[str] = ["form_title", "form_id", "version", "default_language", "style"]


def _env(name: str, default: str) -> str:
    return os.environ.get(f"XLSFS_{name}", default)


@dataclass
class Settings:
    """Runtime settings, overridable through ``XLSFS_*`` environment vars."""

    output_dir: Path = field(default_factory=lambda: Path(_env("OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR))))
    default_version_format: str = "%Y%m%d%H%M"


CONFIG = Settings()
