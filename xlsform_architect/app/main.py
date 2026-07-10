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
    python -m xlsform_architect.app.main survey.docx --title "Household Survey"
    python -m xlsform_architect.app.main form.json --output ./out
    python -m xlsform_architect.app.main survey.docx --rules ./my_rules

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

from .config import CONFIG
from .workflow import Workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xlsform-architect",
        description="Transform a questionnaire into a deployment-ready XLSForm package.")
    parser.add_argument("input", help="Questionnaire file "
                        "(.json .csv .xlsx .xls .docx .pdf .txt .md)")
    parser.add_argument("--target", "-t", choices=["kobo", "surveycto", "odk"],
                        default=None,
                        help="Deployment platform: validates against that "
                             "platform's standards and writes its column "
                             "dialect (e.g. SurveyCTO's 'relevance')")
    parser.add_argument("--title", help="Override the form title")
    parser.add_argument("--form-id", help="Override the form id")
    parser.add_argument("--version", help="Override the form version")
    parser.add_argument("--rules", default=None,
                        help="Path to a custom rules directory (defaults to the "
                             "bundled standard XLSForm rules)")
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

    knowledge = None
    if args.rules:
        from pathlib import Path as _P

        from ..engine.knowledge_base import KnowledgeBase
        knowledge = KnowledgeBase.load(directory=_P(args.rules))

    workflow = Workflow(knowledge=knowledge)
    print(f"Processing: {input_path}")
    result = workflow.run_from_file(
        input_path,
        form_title=args.title,
        form_id=args.form_id,
        version=args.version,
        target=args.target,
        output_dir=args.output,
        progress=None if args.quiet else _progress,
    )

    report = result.report
    print()
    print(f"Form:    {result.questionnaire.settings.form_title}")
    print(f"Form id: {result.questionnaire.settings.form_id}")
    print(f"Version: {result.questionnaire.settings.version}")
    if result.target:
        print(f"Target:  {result.target.upper()} "
              f"(platform standards applied; dialect columns written)")
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
