"""Command-line entry point.

Purpose
-------
Run the full XLSForm Studio pipeline from a terminal, without Streamlit.
Useful for batch processing, automation and CI.

Usage
-----
    python -m xlsform_studio.app.main INPUT [options]

Examples
--------
    python -m xlsform_studio.app.main survey.docx --title "Household Survey"
    python -m xlsform_studio.app.main form.json --output ./out
    python -m xlsform_studio.app.main survey.docx --rules ./my_rules

    # Optional AI enrichment (requires DEEPSEEK_API_KEY):
    python -m xlsform_studio.app.main survey.docx --ai
    python -m xlsform_studio.app.main survey.docx --ai --ai-features translate,review \
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
import os
import sys
from pathlib import Path

from ..ai.client import DeepSeekClient
from ..ai.config import AI_FEATURES, AIConfig, normalize_features
from ..logging_config import configure_logging
from ..validation.report_generator import CONFIDENCE_ICONS
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
        prog="xlsform-studio",
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
    parser.add_argument("--log-level", default="WARNING",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Diagnostic log verbosity to stderr (default: "
                             "WARNING; use DEBUG to trace each AI feature "
                             "and network call)")
    parser.add_argument("--packs", default="",
                        help="Comma-separated domain rule packs to merge on "
                             "top of the neutral rules (e.g. "
                             "'nutrition,health'); see knowledge/packs/")
    parser.add_argument("--no-path-analysis", action="store_true",
                        help="Skip the static path analysis (enumerating "
                             "enumerator paths through the skip logic to "
                             "verify every expression's references hold a "
                             "value where they run); on by default")
    parser.add_argument("--diff-against", metavar="OLD_FILE",
                        help="Also compare against a previous questionnaire "
                             "version (any supported format); writes "
                             "change_report.md into the output package and "
                             "prints a summary")
    parser.add_argument("--simulate", action="store_true",
                        help="After compiling, run an interactive interview "
                             "simulation in the terminal: answer questions and "
                             "watch skips, constraints, calculations and "
                             "repeats fire in real time")
    parser.add_argument("--from-model", metavar="MODEL_JSON",
                        help="Round-trip re-import: treat INPUT as an edited "
                             "XLSForm and reconcile it against this model "
                             "snapshot (the '*_model.json' sidecar from the "
                             "run that produced it). Preserves per-field "
                             "confidence and the assumptions log for fields "
                             "you didn't change; requires no API key")

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
                         "AI authoring and the 'review'/'completeness' features")
    ai.add_argument("--ai-objectives", default="",
                    help="Study objectives for the 'coverage' feature: either "
                         "inline text (';'-separated) or a path to a text "
                         "file with one objective per line")
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
            ("--ai-instructions", "instructions",
             "draft enumerator instructions as device hints")):
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
    configure_logging(args.log_level)
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"error: input file not found: {input_path}", file=sys.stderr)
        return 2

    knowledge = None
    pack_names = [p.strip() for p in args.packs.split(",") if p.strip()]
    if args.rules or pack_names:
        from pathlib import Path as _P

        from ..engine.knowledge_base import KnowledgeBase
        try:
            knowledge = KnowledgeBase.load(
                directory=_P(args.rules) if args.rules else None,
                packs=pack_names)
        except FileNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    # AI authoring is essential (the model drafts every form field), so a
    # DeepSeek client is created up front and reused for any enrichment. The
    # deterministic rule-engine seam (XLSFS_AUTHORING=deterministic) is the
    # only way to run without a key, and is not a documented product mode.
    authoring_mode = os.environ.get("XLSFS_AUTHORING", "ai").lower()
    ai_client = DeepSeekClient()
    if not ai_client.available:
        ai_client = None

    ai_config = AIConfig.disabled()
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
        objectives = args.ai_objectives
        if objectives and Path(objectives).is_file():
            objectives = Path(objectives).read_text(encoding="utf-8")
        elif objectives:
            objectives = "\n".join(p.strip() for p in objectives.split(";")
                                   if p.strip())
        ai_config = AIConfig(enabled=True, features=features,
                             translate_languages=_parse_languages(args.ai_languages),
                             survey_context=args.ai_context,
                             objectives=objectives)

    # Round-trip re-import authors nothing (the model came from a prior run),
    # so it never needs a key - even though enrichment still may.
    if not args.from_model and authoring_mode != "deterministic" \
            and ai_client is None:
        print("error: a DeepSeek API key is required (set DEEPSEEK_API_KEY). "
              "XLSForm Studio drafts every form with AI and has no offline "
              "authoring mode.", file=sys.stderr)
        return 2

    workflow = Workflow(knowledge=knowledge, ai_client=ai_client)
    if args.from_model:
        model_path = Path(args.from_model)
        if not model_path.exists():
            print(f"error: model snapshot not found: {model_path}",
                  file=sys.stderr)
            return 2
        print(f"Re-importing edited XLSForm: {input_path}")
        print(f"Reconciling against model:   {model_path}")
        try:
            result = workflow.run_roundtrip(
                input_path, model_path,
                form_title=args.title,
                form_id=args.form_id,
                version=args.version,
                target=args.target,
                output_dir=args.output,
                ai_config=ai_config,
                survey_context=args.ai_context,
                path_analysis=not args.no_path_analysis,
                progress=None if args.quiet else _progress,
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    else:
        print(f"Processing: {input_path}")
        result = workflow.run_from_file(
            input_path,
            form_title=args.title,
            form_id=args.form_id,
            version=args.version,
            target=args.target,
            output_dir=args.output,
            ai_config=ai_config,
            survey_context=args.ai_context,
            path_analysis=not args.no_path_analysis,
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
    if result.quality is not None:
        print()
        print(f"Form Quality Index: {result.quality.overall}/100 "
              f"({result.quality.rating})")
        for name, score in result.quality.categories.items():
            print(f"   {name.replace('_', ' '):22} {score}/100")
    if result.duration is not None:
        d = result.duration
        print(f"Estimated interview: ~{d.typical_minutes:.0f} min "
              f"(range {d.low_minutes:.0f}-{d.high_minutes:.0f}); "
              f"burden risk: {d.burden_risk}")
    if result.design is not None:
        print()
        print(f"Survey Design Score: {result.design.overall}/100 "
              f"({result.design.rating})")
        for dim in result.design.dimensions:
            sc = f"{dim.score}/100" if dim.assessed else "not assessed"
            print(f"   {dim.name.replace('_', ' '):26} {sc}")

    print()
    print("Validation:", "PASSED" if report.is_valid else "FAILED")
    print(" ", report.summary())
    if report.findings:
        print("  Confidence: ✅ confirmed by toolchain   🔎 checked by this "
              "tool   🧭 heuristic - review needed   ❔ unsupported/passed "
              "through")
    for f in report.sorted_findings():
        loc = f" [{f.location}]" if f.location else ""
        icon = CONFIDENCE_ICONS.get(f.confidence, "")
        print(f"   - {f.level.upper():7} {icon} {f.category}{loc}: {f.message}")
        if f.explanation:
            print(f"             → {f.explanation}")

    if result.review_table:
        attention = [r for r in result.review_table if r.needs_attention]
        print()
        print(f"Parser decisions ({len(result.review_table)}) — heuristic "
              f"type/choice-list/relevance/constraint inferences; review "
              f"and edit in the app, or in assumptions_to_verify.md:")
        if attention:
            print(f"   {len(attention)} item(s) could NOT be inferred at "
                  f"all and need your input:")
            for row in attention:
                print(f"   - [{row.field_label}] '{row.question}': "
                      f"{row.reason}")

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

    if args.diff_against:
        old_path = Path(args.diff_against)
        if not old_path.exists():
            print(f"error: --diff-against file not found: {old_path}",
                 file=sys.stderr)
        else:
            from ..analysis.diff import QuestionnaireDiff
            from ..parsers.factory import parse_file
            old_qn, _ = workflow.engine.compile(parse_file(old_path))
            diff = QuestionnaireDiff.compare(old_qn, result.questionnaire)
            folder = result.outputs.get("folder")
            if folder:
                diff_path = Path(folder) / "change_report.md"
                diff_path.write_text(diff.to_markdown(), encoding="utf-8")
                result.outputs["change_report"] = diff_path
            print()
            if not diff.has_changes:
                print(f"Changes vs {old_path.name}: none - identical forms.")
            else:
                print(f"Changes vs {old_path.name}: "
                      f"{len(diff.added)} added, {len(diff.removed)} removed, "
                      f"{len(diff.renamed)} renamed, "
                      f"{len(diff.field_changes)} field change(s), "
                      f"{len(diff.list_changes) + len(diff.lists_added) + len(diff.lists_removed)} "
                      f"choice-list change(s) - see change_report.md")

    print()
    print("Output package:")
    for key, path in result.outputs.items():
        print(f"   {key:18} {path}")

    if args.simulate:
        run_simulation(result.questionnaire)

    return 0 if report.is_valid else 1


def run_simulation(questionnaire, input_fn=input, out=None) -> None:
    """Drive an interactive interview at the terminal.

    ``input_fn`` / ``out`` are injectable so the loop can be scripted in a
    test without a real TTY.
    """
    from ..app.simulator import Interview

    def emit(text: str = "") -> None:
        print(text, file=out)

    sim = Interview(questionnaire)
    emit()
    emit("=" * 60)
    emit("  Interview simulation — answers drive the live logic.")
    emit("  Enter a value; blank = leave empty; 'q' = quit.")
    emit("  For select_multiple, separate codes with spaces.")
    emit("=" * 60)

    while True:
        step = sim.current()
        if step.kind == "done":
            emit()
            emit("Interview complete.")
            _print_sim_summary(sim, emit)
            return

        if step.kind == "repeat_prompt":
            emit()
            prompt = (f"[{step.path}] Add another '{step.repeat_label}'? "
                      f"({step.completed_instances} so far) [y/N/q] ")
            answer = input_fn(prompt).strip().lower()
            if answer == "q":
                emit("Simulation ended.")
                return
            if answer in ("y", "yes"):
                sim.add_repeat_instance()
            else:
                sim.finish_repeat()
            continue

        q = step.question
        emit()
        crumb = f"[{step.path}] " if step.path else ""
        flag = " *" if q.required else ""
        emit(f"{crumb}{q.label or q.name}{flag}")
        if q.hint:
            emit(f"  ({q.hint})")
        for c in step.choices:
            emit(f"    {c.name} = {c.label}")
        raw = input_fn("> ")
        if raw.strip().lower() == "q":
            emit("Simulation ended.")
            return
        result = sim.submit(raw)
        if not result.ok:
            emit(f"  ✗ {result.error}")
            continue
        # Echo what just fired: newly skipped questions and live calcs.
        state = sim.state()
        for ev in state.events[-6:]:
            if ev.kind == "skipped":
                emit(f"  → skipped '{ev.label}' ({ev.detail})")
        calcs = [c for c in state.calculations if c.value]
        if calcs:
            emit("  = " + ", ".join(f"{c.name}={c.value}" for c in calcs))


def _print_sim_summary(sim, emit) -> None:
    state = sim.state()
    emit()
    emit(f"Answered {len(state.answered)}, skipped {len(state.skipped)}.")
    if state.answered:
        emit("Answers:")
        for a in state.answered:
            crumb = f"[{a.path}] " if a.path else ""
            emit(f"   {crumb}{a.name} = {a.value or '(blank)'}")
    calcs = [c for c in state.calculations if c.value]
    if calcs:
        emit("Calculations:")
        for c in calcs:
            emit(f"   {c.name} = {c.value}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
