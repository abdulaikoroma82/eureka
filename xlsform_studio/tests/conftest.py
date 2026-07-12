"""Shared pytest configuration for the XLSForm Studio test suite.

The product pipeline is AI-first: :class:`~xlsform_studio.app.workflow.Workflow`
drafts every form field with the DeepSeek model and has no offline authoring
fallback (see ``DEFAULT_AUTHORING``). The bulk of the suite, however, exercises
the *deterministic* layers the AI is checked against - parsers, the rule
engine, choice normalisation, the exporter's platform dialects, and the
validators - none of which should require a network call or an API key.

Selecting the deterministic authoring seam for the whole session lets those
tests keep compiling questionnaires with the rule engine exactly as before.
Tests that specifically cover the AI-first path override this per run by
passing ``authoring="ai"`` with a fake client (the per-call argument wins
over this environment default)."""

import os

# Set before any workflow import reads it. The per-run ``authoring`` argument
# still overrides this, so AI-first tests are unaffected.
os.environ.setdefault("XLSFS_AUTHORING", "deterministic")
