"""Command-line entry point.

Purpose
-------
Run the full XLSForm Architect pipeline from a terminal, without Streamlit.
Useful for batch processing, automation and CI.

Usage
-----
    python -m xlsform_architect.app.main INPUT [options]

Examples
--------
    python -m xlsform_architect.app.main survey.docx --category imam
    python -m xlsform_architect.app.main form.json --title "OTP Register" \
        --output ./out

Inputs
------
Any supported questionnaire file (.json .csv .xlsx .xls .docx .pdf).

Outputs
-------
Writes the full output package to the output directory and prints a summary.
Exit code is non-zero when validation fails.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import CONFIG, SURVEY_CATEGORIES
from .workflow import Workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xlsform-architect",
        description="Transform a questionnaire into a deployment-ready XLSForm package.")
    parser.add_argument("input", help="Questionnaire file (.json .csv .xlsx .xls .docx .pdf)")
    parser.add_argument("--title", help="Override the form title")
    parser.add_argument("--form-id", help="Override the form id")
    parser.add_argument("--version", help="Override the form version")
    parser.add_argument("--category", choices=SURVEY_CATEGORIES, default=None,
                        help="Survey category / knowledge pack")
    parser.add_argument("--output", "-o", default=str(CONFIG.output_dir),
                        help="Output directory")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress step output")
    return parser


def _progress(step: str, status: str) -> None:
    if status == "done":
        print(f"  [x] {step}")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"error: input file not found: {input_path}", file=sys.stderr)
        return 2

    workflow = Workflow()
    print(f"Processing: {input_path}")
    result = workflow.run_from_file(
        input_path,
        form_title=args.title,
        form_id=args.form_id,
        version=args.version,
        category=args.category,
        output_dir=args.output,
        progress=None if args.quiet else _progress,
    )

    report = result.report
    print()
    print(f"Form:    {result.questionnaire.settings.form_title}")
    print(f"Form id: {result.questionnaire.settings.form_id}")
    print(f"Version: {result.questionnaire.settings.version}")
    print(f"Questions compiled: "
          f"{len([q for q in result.questionnaire.questions if q.base_type not in ('begin group', 'end group')])}")
    print()
    print("Validation:", "PASSED" if report.is_valid else "FAILED")
    print(" ", report.summary())
    for f in report.sorted_findings():
        loc = f" [{f.location}]" if f.location else ""
        print(f"   - {f.level.upper():7} {f.category}{loc}: {f.message}")

    print()
    print("Compatibility:")
    for platform, ok in report.compatibility.items():
        print(f"   {platform.upper():10} {'OK' if ok else 'FAILED'}")

    print()
    print("Output package:")
    for key, path in result.outputs.items():
        print(f"   {key:18} {path}")

    return 0 if report.is_valid else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
