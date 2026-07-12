# XLSForm Studio — Capability Roadmap

Status of every module from the capability-gap review, prioritized by
impact versus effort. Architecture invariants that every item must
preserve: **deterministic-first** (rules are the authority), **offline-first**
(AI optional, zero AI dependency for core compilation), **full auditability**
(assumption log + deterministic outputs), **YAML-driven rules**, **platform
neutrality**.

Legend: ✅ shipped · 🚫 descoped · ⭐ signature capability

---

## Status summary

| # | Module | Status | Where |
| --- | --- | --- | --- |
| D2 | Visual Logic Mapper | ✅ | `app/logic_flow.py` (ASCII + Graphviz + interactive UI chart) |
| D3 | Questionnaire Difference Engine | ✅ | `analysis/diff.py`, CLI `--diff-against` |
| D4 | Form Quality Scoring Engine | ✅ | `analysis/quality_score.py`, QA report + Quality tab |
| D5 | Advanced Consistency Validator | ✅ | `validation/consistency_validator.py` |
| D8 | Survey Duration Estimator | ✅ | `analysis/duration.py`, QA report + Quality tab |
| D9 | Choice List Normalization | ✅ | `engine/choice_normalizer.py` (exact merges) + D5 (near-identical flags) |
| A3 | Respondent Experience Review | ✅ | `ai/quality_reviewer.py` (respondent-experience category) |
| A6 | Duplicate Concept Detection | ✅ | `ai/quality_reviewer.py` (redundant-question checks) |
| A7 | Bias Detection | ✅ | `ai/rewording.py` (leading/double-barreled/jargon, with reasons) |
| A10 | Choice Quality Review | ✅ | `ai/quality_reviewer.py` + `ai/choice_ordering.py` |
| A12 | Survey Structure Optimization | ✅ | `ai/grouping.py` (suggestion-only sections) |
| A13 | Semantic Constraint Suggestions | ✅ | Single-field bounds now produced by `ai/form_author.py` (AI authoring); cross-field via `ai/constraint_reviewer.py` |
| A15 | Survey Quality Narrative | 🚫 | descoped — see *Descoped items* below |
| A16 | Document co-writing (guide, plan, logic map, instrument, checklist) | 🚫 | descoped — see *Descoped items* below |
| H1 | Survey Health Score | ✅ | D4 Form Quality Index (`analysis/quality_score.py`) + the Survey Design Score (S1) |
| H3 | Smart Assumption Log | 🚫 | descoped — see *Descoped items* below |
| H4 | Smart Validation Report | ✅ | `ai/finding_explainer.py` |
| H5 | Readiness Assessment | ✅ | `validation/readiness_validator.py` (translation/media/device/metadata completeness) surfaced in the QA report |
| D6 | Metadata & Documentation Generator | ✅ | `app/artifacts.py`: enumerator guide, variable specification, collection plan |
| A9 | Enumerator Instruction Generator | ✅ | `ai/enumerator_notes.py` (advisory `hint` suggestions; author hints win) |
| D10 | Deployment Readiness Checks | ✅ | `validation/readiness_validator.py` (translation/media/device/metadata completeness) + platform matrix + pyxform deep check |
| A1 | Methodology Expert Review | ✅ | `ai/quality_reviewer.py` (expert-panel category 5: sequencing, priming, sensitive-question placement) |
| D7 | Domain Rule Packs | ✅ | `knowledge/packs/*.yaml` (nutrition, health, agriculture, education, humanitarian) + `KnowledgeBase.load(packs=...)`, CLI `--packs`, UI multiselect |
| A4 | Missing Question Detection | ✅ | `ai/completeness.py` (advisory findings; never adds questions) |
| A5 | Objective Coverage Review | ✅ | `ai/coverage.py` (objectives via UI textarea / `--ai-objectives`) |
| H2 | Coverage Matrix | ✅ | `coverage_matrix.md` artifact + Quality tab; question refs verified deterministically |
| A2 | Enumerator Experience Review | ✅ | `ai/quality_reviewer.py` (expert-panel category 4: transitions, probing burden, recording pitfalls) |
| A8 | Indicator Mapping Engine | ✅ | `ai/indicators.py` → `indicator_matrix.md` + Quality tab; question refs verified deterministically |
| A14 | Semantic Logic Review | ✅ | D5 owns decidable defects; `ai/quality_reviewer.py` category 5 reviews conceptual pathways |
| D1 | Reverse Engineering Engine | ✅ | `parsers/excel_parser.py` reads XLSForms (incl. SurveyCTO dialect); importing one regenerates the full documentation package; printable `*_survey_instrument.docx` in every package |
| S1 | ⭐ Survey Design Intelligence | ✅ | `analysis/design_intelligence.py` — deterministic **Survey Design Score** (0–100) across ten methodological dimensions: question order, module flow, cognitive burden, recall-period consistency, scale consistency, enumerator/respondent burden, objective coverage, redundancy, measurement validity. Rating gated by the weakest dimension; folds in AI-reviewer findings when present but never requires them; vocabularies in `knowledge/design_intelligence.yaml`. Renders in QA report, Quality tab, CLI, and `survey_design_report.md`. Moves the tool from form *generation* into survey **methodology assistance**. |
| D11 | Round-trip editing | ✅ | `app/provenance.py` (model sidecar `*_model.json`, written every run) + `app/roundtrip.py` (field-level reconcile, incl. rename detection by label) + `Workflow.run_roundtrip`, CLI `--from-model`, UI sidebar "5 · ♻️ Re-import an edited XLSForm"; re-imports an edited XLSForm without losing per-field confidence or the assumptions log, never re-authoring — makes the tool a canonical editor, not just a generator |
| A11 | Domain Plausibility Review | 🚫 | descoped — see *Descoped items* below |
| D2 | Visual mapper extensions (SVG/PNG) | 🚫 | descoped — see *Descoped items* below |

---

## Descoped items

Several items were reviewed and cut rather than kept half-used, to keep the
product focused on survey **engineering** and methodology rather than prose
polish, and to reduce API usage and maintenance:

* **A16 — AI document co-writing.** The supporting documents (enumerator
  guide, collection plan, logic map, printable instrument, assumptions
  checklist) are authored deterministically and already contain every fact.
  AI only rewrote their introductory *prose*, which reads a little more
  naturally but changes nothing about the tool's engineering value. Removing
  it cut an API call per form, simplified the artefact builders (no prose
  slotting, no `DocumentProse`), and made every document byte-for-byte
  reproducible again. Cut.
* **A15 / H1 narration — AI quality narrative.** The QA report's executive
  summary was AI-written from the deterministic metrics. A deterministic
  headline ("scored 92/100 with three warnings and no blocking errors") plus
  the Form Quality Index and Survey Design Score tables carry the same
  information; the narrative was cosmetic. Cut (the Survey Health Score, H1,
  now reads straight from D4 + S1).
* **Variable-name suggestions (`ai/naming.py`).** The deterministic namer is
  stable, reproducible and standards-compliant by design; an AI alternative
  introduced a second naming option most teams would never adopt, and a
  stable name is exactly what version history and diffs need. Renaming stays
  available — manually, in the review panel, with automatic `${...}`
  reference rewriting — without a suggestion engine. Cut.
* **A11 — pack-aware domain plausibility.** Survey-context grounding,
  domain packs (D7), and the completeness review (A4) already cover the
  practical need — flagging a plausibly missing question or an
  out-of-range value. A fourth, narrower AI call to check pack vocabulary
  specifically added a fourth API round-trip per form for marginal
  incremental signal over what A4 already surfaces. Cut.
* **H3 — smart assumption-log explanations.** The assumption log already
  records every automatic decision in plain language at the point it is
  made (`app/artifacts.py`). A second AI pass to re-explain entries that
  are already human-readable was redundant with H4's finding explainer. Cut.
* **D2 — SVG/PNG rendering.** The DOT and Mermaid sources already ship in
  every output package and render natively (Mermaid on GitHub/GitLab/most
  wikis; DOT in any Graphviz viewer or the in-app chart). Shelling out to
  an optional system `graphviz` binary to pre-render a raster image would
  add a platform-dependent code path for a format users can already
  generate themselves in one click. Cut.

If real usage surfaces a concrete need for any of these, they should be
re-scoped from first principles rather than resumed from a partial state.

---

## Standing acceptance criteria (all modules)

1. `pytest` green; no existing test modified except to extend.
2. Zero network calls unless an AI feature is explicitly enabled AND keyed.
3. Deterministic modules: identical output on identical input, byte-for-byte.
4. AI modules: one API call per form per feature; validated before use;
   rejected output logged, never applied; advisory findings capped at
   `warning`; fail-open to the deterministic result.
5. Every automatic decision lands in the assumption log; every AI decision
   is tagged "AI-suggested".
6. Rules/config in YAML, not code, wherever a non-programmer might edit them.
