#!/usr/bin/env python3
"""Compile an authored questionnaire JSON into a validated XLSForm package.

This is the deterministic half of the questionnaire-to-xlsform skill. The
model (Claude) does the interpretive authoring — reading the source
questionnaire and expressing it as the structured JSON this script consumes.
This script then runs XLSForm Studio's deterministic pipeline (classify →
name → build logic/constraints/calculations → normalise choices → export →
validate), so every field name, XPath expression and choice list is produced
and checked by rules rather than guessed, and the result is a real, validated
XLSForm rather than a hand-typed spreadsheet.

Authoring is forced to ``deterministic`` so no ``DEEPSEEK_API_KEY`` is needed:
Claude has already played the role of the AI author by producing the JSON.

Usage
-----
    python generate.py FORM.json --target kobo --output ./out

Reads FORM.json (see references/json-schema.md for the schema), writes the
full package to the output directory, prints a review-focused summary, and
exits non-zero if validation finds blocking errors so the model knows to fix
the JSON and re-run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _find_studio() -> None:
    """Make ``xlsform_studio`` importable.

    The skill pairs with the XLSForm Studio repository. If the package is not
    already installed (``pip install -r requirements.txt`` at the repo root),
    walk up from this script looking for a checkout so the skill still works
    when it is bundled next to, or inside, the repo.
    """
    try:
        import xlsform_studio  # noqa: F401
        return
    except ImportError:
        pass
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "xlsform_studio" / "__init__.py").exists():
            sys.path.insert(0, str(parent))
            return
    # Leave it to fail with a clear message at import time below.


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Compile authored questionnaire JSON into a validated "
                    "XLSForm package (deterministic; no API key needed).")
    parser.add_argument("input", help="Path to the authored questionnaire JSON")
    parser.add_argument("--target", "-t", default=None,
                        help="Deployment platform: kobo | surveycto | odk | "
                             "ona | commcare (validates against and writes "
                             "that platform's column dialect)")
    parser.add_argument("--title", default=None, help="Override the form title")
    parser.add_argument("--form-id", default=None, help="Override the form id")
    parser.add_argument("--version", default=None, help="Override the version")
    parser.add_argument("--output", "-o", default="./xlsform_output",
                        help="Output directory (default: ./xlsform_output)")
    args = parser.parse_args(argv)

    _find_studio()
    try:
        from xlsform_studio.app.workflow import Workflow
    except ImportError:
        sys.stderr.write(
            "ERROR: xlsform_studio is not importable. Install the engine "
            "first, e.g. from the repo root:\n"
            "    pip install -r requirements.txt\n"
            "or `pip install -e .`, then re-run.\n")
        return 2

    src = Path(args.input)
    if not src.exists():
        sys.stderr.write(f"ERROR: input file not found: {src}\n")
        return 2
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"ERROR: {src} is not valid JSON: {exc}\n")
        return 2

    result = Workflow().run_from_dict(
        data,
        authoring="deterministic",     # Claude already authored the JSON
        target=(args.target or "").lower() or None,
        form_title=args.title,
        form_id=args.form_id,
        version=args.version,
        output_dir=args.output,
        source_name=src.stem,
    )

    report = result.report
    print("=" * 68)
    print(f"Validation: {'PASSED' if report.is_valid else 'FAILED'}")
    print("  " + report.summary())

    for f in report.errors:
        print(f"  ERROR   [{f.location or '-'}]: {f.message}")
    for f in report.warnings:
        print(f"  WARNING [{f.location or '-'}]: {f.message}")

    print("\nOutput package:")
    for key in ("xlsform", "data_dictionary", "assumptions_to_verify",
                "validation_report", "logic_map", "folder"):
        if key in result.outputs:
            print(f"  {key:22s} {result.outputs[key]}")

    if result.assumptions:
        print(f"\n{len(result.assumptions)} parser decision(s) recorded in "
              "assumptions_to_verify.md — review the heuristic type / choice / "
              "relevance / constraint inferences.")

    if not report.is_valid:
        print("\nValidation failed: fix the flagged fields in the JSON and "
              "re-run.")
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        # Output was piped to a reader that closed early (e.g. `head`).
        sys.exit(0)
