"""XLSForm Architect.

A standalone, rule-based questionnaire-to-XLSForm compiler.

The package turns questionnaires (DOCX / XLSX / PDF / CSV / structured JSON)
into deployment-ready XLSForms that are compatible with KoboToolbox,
SurveyCTO and ODK.

The system is fully deterministic: all intelligence comes from parsers,
rule engines, templates and validators.  It does NOT depend on any external
AI or subscription service.
"""

__version__ = "1.0.0"
__all__ = ["__version__"]
