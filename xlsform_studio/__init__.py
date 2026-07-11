"""XLSForm Studio.

An offline survey engineering platform that automatically transforms
questionnaires (DOCX / XLSX / PDF / CSV / structured JSON) into validated,
deployment-ready XLSForms compatible with KoboToolbox, SurveyCTO, ODK, Ona
and CommCare. Under the hood, it works as a deterministic
questionnaire-to-XLSForm compiler with an optional AI layer.

The core pipeline is fully deterministic: parsers, rule engines, templates
and validators, with zero network activity and zero AI dependency by
default. An optional AI-assist layer (``xlsform_studio.ai``, DeepSeek)
can be explicitly enabled for the handful of tasks that are inherently
language/reasoning problems a rule engine cannot solve: translation,
resolving skip-to-question jumps and unparseable conditional logic,
suggesting cross-field constraints (e.g. an end date after a start date),
classifying ambiguous questions, a holistic semantic and naming-clarity
review, and plain-English explanations of the validator's own findings. On
several of these, rules and AI genuinely co-author the same output (e.g. a
combined single-field + cross-field constraint) rather than one handing off
to the other - always with rules as the authoritative party and AI strictly
supplementing, never silently overwriting. AI requires an explicit opt-in
and an API key; with neither, the tool's behaviour is unchanged.
"""

__version__ = "1.12.0"
__all__ = ["__version__"]
