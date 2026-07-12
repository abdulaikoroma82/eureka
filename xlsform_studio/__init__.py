"""XLSForm Studio.

An online, AI-first survey engineering platform that automatically transforms
questionnaires (DOCX / XLSX / PDF / CSV / structured JSON) into validated,
deployment-ready XLSForms compatible with KoboToolbox, SurveyCTO, ODK, Ona
and CommCare.

Pipeline
--------
The model is the author; deterministic rules bracket it on both sides:

1. Parse (deterministic) lays out the scaffold - the items and the exact
   sheets/columns for the target platform's dialect.
2. **AI authors the form** (``xlsform_studio.ai.form_author``, DeepSeek):
   the model interprets the questionnaire and drafts every field - types,
   machine names, labels, hints, relevance/skip logic, constraints,
   calculations and choice lists - into those standardized sections.
3. Deterministic rules enforce standards (unique/valid names, choice
   normalisation) and validate the draft (XPath syntax, dead values,
   platform limits), so the AI is held to the platform's rules.
4. The human reviews and edits the AI draft before download.

AI is essential, not optional: a run requires a configured DeepSeek API key
and there is no offline authoring fallback in the shipped product. The
legacy fully-deterministic compiler survives only as an internal
standards/test seam (``authoring="deterministic"`` / ``XLSFS_AUTHORING``),
never selected by the UI or CLI.
"""

__version__ = "2.0.0"
__all__ = ["__version__"]
