"""XLSForm Architect.

A rule-based questionnaire-to-XLSForm compiler with an optional AI layer.

The package turns questionnaires (DOCX / XLSX / PDF / CSV / structured JSON)
into deployment-ready XLSForms compatible with KoboToolbox, SurveyCTO, ODK,
Ona and CommCare.

The core pipeline is fully deterministic: parsers, rule engines, templates
and validators, with zero network activity and zero AI dependency by
default. An optional AI-assist layer (``xlsform_architect.ai``, DeepSeek)
can be explicitly enabled for the handful of tasks - translation, inverting
"skip to question N" logic, classifying ambiguous questions, and a semantic
quality review - that are inherently language/reasoning problems a rule
engine cannot solve. It requires an explicit opt-in and an API key; with
neither, the tool's behaviour is unchanged.
"""

__version__ = "1.2.0"
__all__ = ["__version__"]
