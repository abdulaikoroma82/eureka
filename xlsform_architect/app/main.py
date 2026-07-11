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

    # Optional AI enrichment (requires DEEPSEEK_API_KEY):
    python -m xlsform_architect.app.main survey.docx --ai
    python -m xlsform_architect.app.main survey.docx --ai --ai-features translate,review \
        --ai-languages "French:fr,Spanish:es"

Inputs
------
Any supported questionnaire file (.json .csv .xlsx .xls .docx .pdf .txt .md).

Outputs
-------
Writes the full output package to the output directory and prints a summary.
Exit code is non-zero when validation fails. AI enrichment (if requested) is
strictly additive and never affects the deterministic exit code semantics.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..ai.client import DeepSeekClient
from ..ai.config import AI_FEATURES, AIConfig, normalize_features
from .config import CONFIG, DEPLOYMENT_TARGETS
from .workflow import Workflow


def _available_targets() -> list:
    """Platform keys from the knowledge pack (YAML-driven), with a fallback."""
    try:
        from ..engine.knowledge_base import KnowledgeBase
        names = KnowledgeBase.load().platform_names()
        if names:
            return names
    except Exception:  # pragma: no cover - defensive
        pass
    return list(DEPLOYMENT_TARGETS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xlsform-architect",
        description="Transform a questionnaire into a deployment-ready XLSForm package.")
    parser.add_argument("input", help="Questionnaire file "
                        "(.json .csv .xlsx .xls .docx .pdf .txt .md)")
    parser.add_argument("--target", "-t", choices=_available_targets(),
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

    ai = parser.add_argument_group(
        "optional AI enrichment (DeepSeek)",
        "Opt-in only; requires the DEEPSEEK_API_KEY environment variable. "
        "The deterministic pipeline is unaffected if omitted.")
    ai.add_argument("--ai", action="store_true",
                    help="Enable AI-assisted enrichment")
    ai.add_argument("--ai-features", default=",".join(AI_FEATURES),
                    help=f"Comma-separated subset of: {','.join(AI_FEATURES)} "
                         f"(default: all)")
    ai.add_argument("--ai-languages", default="",
                    help="Comma-separated Name:code pairs for translation, "
                         "e.g. 'French:fr,Spanish:es' (requires --ai-features "
                         "to include 'translate')")
    ai.add_argument("--ai-context", default="",
                    help="Free-text description of the survey's domain, e.g. "
                         "'child nutrition survey in rural districts'; grounds "
                         "the 'domain_constraints' and 'review' features")
    # Standalone shortcuts: each enables AI with just that feature (they
    # combine with each other, and with --ai/--ai-features if also given).
    for flag, feature, text in (
            ("--ai-group", "group", "suggest logical question sections"),
            ("--ai-rewrite", "rewrite", "suggest clearer question wording"),
            ("--ai-order", "order", "suggest logical choice-list ordering"),
            ("--ai-cross", "cross_constraints",
             "suggest cross-field constraints"),
            ("--ai-review", "review", "run the AI quality review"),
            ("--ai-explain", "explain_findings",
             "explain validation findings in plain English"),
            ("--ai-name", "naming", "suggest clearer variable names")):
        ai.add_argument(flag, dest=f"ai_flag_{feature}", action="store_true",
                        help=f"Shortcut: {text} (implies --ai with this "
                             f"feature)")
    return parser


def _parse_languages(raw: str) -> list:
    languages = []
    for part in filter(None, (p.strip() for p in raw.split(","))):
        name, _, code = part.partition(":")
        if name and code:
            languages.append((name.strip(), code.strip()))
    return languages


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

    ai_config = AIConfig.disabled()
    ai_client = None
    flag_features = [f for f in AI_FEATURES
                     if getattr(args, f"ai_flag_{f}", False)]
    if args.ai or flag_features:
        if args.ai:
            features = normalize_features(
                f.strip() for f in args.ai_features.split(",") if f.strip())
        else:
            features = []          # only the standalone flags were given
        features.extend(f for f in flag_features if f not in features)
        unknown = set(features) - set(AI_FEATURES)
        if unknown:
            print(f"error: unknown --ai-features: {', '.join(sorted(unknown))} "
                 f"(choose from: {', '.join(AI_FEATURES)})", file=sys.stderr)
            return 2
        ai_config = AIConfig(enabled=True, features=features,
                             translate_languages=_parse_languages(args.ai_languages),
                             survey_context=args.ai_context)
        ai_client = DeepSeekClient()
        if not ai_client.available:
            print("warning: AI enrichment was requested but DEEPSEEK_API_KEY "
                 "is not set; continuing without it.", file=sys.stderr)

    workflow = Workflow(knowledge=knowledge, ai_client=ai_client)
    print(f"Processing: {input_path}")
    result = workflow.run_from_file(
        input_path,
        form_title=args.title,
        form_id=args.form_id,
        version=args.version,
        target=args.target,
        output_dir=args.output,
        ai_config=ai_config,
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
    if ai_config.enabled:
        print(f"AI:      {'ran (' + ', '.join(ai_config.features) + ')' if result.ai_ran else 'requested but did not run (no API key)'}")
    print(f"Questions compiled: "
          f"{len([q for q in result.questionnaire.questions if not q.is_structural])}")
    print()
    print("Validation:", "PASSED" if report.is_valid else "FAILED")
    print(" ", report.summary())
    for f in report.sorted_findings():
        loc = f" [{f.location}]" if f.location else ""
        print(f"   - {f.level.upper():7} {f.category}{loc}: {f.message}")
        if f.explanation:
            print(f"             → {f.explanation}")

    if result.ai_suggestions:
        print()
        print(f"AI suggestions ({len(result.ai_suggestions)}) — advisory "
              f"only, nothing was changed; review in the app or apply "
              f"manually:")
        for sug in result.ai_suggestions:
            conf = f" (confidence: {sug.confidence})" if sug.confidence else ""
            print(f"   - [{sug.kind}] {sug.target or 'form'}{conf}: "
                  f"{sug.original!r} → {sug.suggested!r}")
            if sug.reason:
                print(f"       reason: {sug.reason}")

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
