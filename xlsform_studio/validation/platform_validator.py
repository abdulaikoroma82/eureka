"""Platform-specific validator.

Purpose
-------
Apply the standards of the *chosen* deployment platform - KoboToolbox,
SurveyCTO or ODK - on top of the generic XLSForm checks.  The rules come
from ``knowledge/platforms.yaml`` (each platform's supported/unsupported
types, naming standards and settings recommendations), so tracking a platform
change is a YAML edit, not a code change.

Checks per target
-----------------
* every question type is supported by the target platform (error if not,
  with a hint when another platform *does* support it)
* platform naming standards (e.g. SurveyCTO: names start with a letter,
  and stay within 32 characters for Stata-friendly exports)
* recommended settings fields are present (info level)

It also computes the honest per-platform **compatibility matrix**: a form
using ``rank`` is compatible with ODK and Kobo but *not* SurveyCTO, and the
matrix now says exactly that instead of one blanket answer.

Inputs
------
A compiled :class:`~xlsform_studio.models.Questionnaire` and a target
platform key (``kobo`` / ``surveycto`` / ``odk``).

Outputs
-------
A list of :class:`Finding` (``validate``) and a ``{platform: bool}`` dict
(``matrix``).

Example
-------
>>> from xlsform_studio.models import Questionnaire, Question
>>> qn = Questionnaire(questions=[Question(name="r", xlsform_type="rank items", label="R")])
>>> any(f.level == "error" for f in PlatformValidator().validate(qn, "surveycto"))
True
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ..engine.knowledge_base import KnowledgeBase
from ..models import Question, Questionnaire
from .report_generator import Finding

_STRUCTURAL = ("begin group", "end group", "begin repeat", "end repeat")


class PlatformValidator:
    """Validate a questionnaire against a specific platform's standards."""

    def __init__(self, knowledge: Optional[KnowledgeBase] = None) -> None:
        self.kb = knowledge or KnowledgeBase.load()

    # ------------------------------------------------------------------
    def validate(self, questionnaire: Questionnaire, target: str) -> List[Finding]:
        profile = self.kb.platform(target)
        if not profile:
            return []
        label = profile.get("label", target.upper())
        findings: List[Finding] = []

        unsupported = {t.lower() for t in profile.get("unsupported_types", [])}
        for q in self._real_questions(questionnaire):
            base = q.base_type.lower()
            if base in unsupported:
                hint = self._supported_elsewhere(base, exclude=target)
                extra = f" (supported on {hint})" if hint else ""
                findings.append(Finding(
                    "error", "platform",
                    f"Type '{q.xlsform_type}' is not supported by {label}{extra}.",
                    q.name))
            findings.extend(self._check_name(q, profile, label))

        findings.extend(self._check_settings(questionnaire, profile, label))
        return findings

    # ------------------------------------------------------------------
    def matrix(self, questionnaire: Questionnaire,
               generally_valid: bool) -> Dict[str, bool]:
        """Per-platform compatibility: generic validity AND no platform errors."""
        result: Dict[str, bool] = {}
        for name in self.kb.platform_names():
            platform_errors = [f for f in self.validate(questionnaire, name)
                               if f.level == "error"]
            result[name] = generally_valid and not platform_errors
        return result

    # ------------------------------------------------------------------
    def _check_name(self, q: Question, profile: dict, label: str) -> List[Finding]:
        findings: List[Finding] = []
        rules = profile.get("name_rules", {}) or {}
        name = q.name or ""
        if not name:
            return findings

        if rules.get("must_start_with_letter") and not name[0].isalpha():
            findings.append(Finding(
                "error", "platform",
                f"{label} requires field names to start with a letter: '{name}'.",
                name))

        max_len = rules.get("max_length")
        if max_len and len(name) > int(max_len):
            findings.append(Finding(
                str(rules.get("max_length_level", "warning")), "platform",
                f"Field name '{name}' exceeds {max_len} characters - "
                f"{rules.get('max_length_reason', f'over the {label} guideline')}.",
                name))
        return findings

    def _check_settings(self, qn: Questionnaire, profile: dict,
                        label: str) -> List[Finding]:
        findings: List[Finding] = []
        recommended = profile.get("settings", {}).get("recommended", [])
        current = {
            "form_title": qn.settings.form_title,
            "form_id": qn.settings.form_id,
            "version": qn.settings.version,
        }
        for key in recommended:
            if key in current and not current[key]:
                findings.append(Finding(
                    "info", "platform",
                    f"{label} recommends setting '{key}' "
                    f"(a default will be generated).", key))
        return findings

    # ------------------------------------------------------------------
    def _supported_elsewhere(self, base_type: str, exclude: str) -> str:
        """Name the platforms that DO support *base_type*, for the error hint."""
        supporters = []
        for name, profile in self.kb.platforms.items():
            if name == exclude:
                continue
            unsupported = {t.lower() for t in profile.get("unsupported_types", [])}
            if base_type not in unsupported:
                supporters.append(profile.get("label", name.upper()))
        return " / ".join(supporters)

    @staticmethod
    def _real_questions(qn: Questionnaire) -> List[Question]:
        return [q for q in qn.questions if q.base_type not in _STRUCTURAL]
