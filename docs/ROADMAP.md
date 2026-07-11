# XLSForm Architect — Capability Roadmap

Status of every module from the capability-gap review, prioritized by
impact versus effort. Architecture invariants that every item must
preserve: **deterministic-first** (rules are the authority), **offline-first**
(AI optional, zero AI dependency for core compilation), **full auditability**
(assumption log + deterministic outputs), **YAML-driven rules**, **platform
neutrality**.

Legend: ✅ shipped · 🟡 partially shipped · ⬜ pending

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
| A13 | Semantic Constraint Suggestions | ✅ | `ai/domain_constraints.py` + `ai/constraint_reviewer.py` |
| A15 | Survey Quality Narrative | ✅ | `ai/narrative.py` |
| H1 | Survey Health Score | ✅ | D4 metrics + A15 narration (`narrative` feature) |
| H3 | Smart Assumption Log | 🟡 | rules record everything; AI explains *findings* but not yet assumptions |
| H4 | Smart Validation Report | ✅ | `ai/finding_explainer.py` |
| D10 | Deployment Readiness Checks | 🟡 | platform matrix + pyxform deep check exist; translation/media/metadata completeness pending |
| A1 | Methodology Expert Review | 🟡 | overlaps quality reviewer; senior-methodologist persona + sequencing review pending |
| A2 | Enumerator Experience Review | ⬜ | pending |
| A4 | Missing Question Detection | ⬜ | pending |
| A5 | Objective Coverage Review | ⬜ | pending |
| A8 | Indicator Mapping Engine | ⬜ | pending |
| A9 | Enumerator Instruction Generator | ⬜ | pending |
| A11 | Domain Plausibility Review | 🟡 | survey-context grounding exists (constraints/review); domain-specific design checks pending |
| A14 | Semantic Logic Review | 🟡 | D5 catches decidable defects; AI review of *conceptual* pathways pending |
| D1 | Reverse Engineering Engine | ⬜ | pending |
| D6 | Metadata & Documentation Generator | ⬜ | pending (data dictionary + logic map already exist) |
| D7 | Domain Rule Packs | ⬜ | pending (loader already supports custom rule dirs via `--rules`) |
| H2 | Coverage Matrix | ⬜ | pending (depends on A5) |
| H5 | Readiness Assessment | ⬜ | pending (depends on D10) |

---

## Recommended implementation order (pending items)

Ranked by impact ÷ effort. Effort scale: **S** ≤ 1 day · **M** ≤ 3 days ·
**L** ≤ 2 weeks.

### Tier 1 — high impact, small/medium effort

**1. D10 — Deployment readiness completion (M)**
- *Architecture*: new `validation/readiness_validator.py`, wired into
  `Validator` after platform checks; per-platform requirements move into
  `knowledge/platforms.yaml` (new `readiness:` block) so they stay YAML-editable.
- *Interface*: `ReadinessValidator.validate(questionnaire, target) -> List[Finding]`.
- *Checks*: translation completeness per declared language column (every
  label/choice/hint translated or listed), media file references present,
  required settings per platform (e.g. SurveyCTO `form_id` length), metadata
  field recommendations.
- *Outputs*: findings (category `readiness`) + a readiness block in the QA report.
- *Tests*: per-check unit tests + a fixture form with one gap per check.
- *Acceptance*: a form with a half-translated French column reports exactly
  which labels are missing; a fully-ready form reports zero readiness findings.

**2. H5 — Readiness assessment hybrid (S, after D10)**
- *Architecture*: extend `ai/narrative.py` (or a sibling `ai/readiness.py`)
  to narrate D10's technical findings and add operational-readiness
  commentary (training implications, deployment sequencing). One API call.
- *Acceptance*: readiness section gains an advisory paragraph; numbers unchanged.

**3. D6 — Metadata & documentation generator (M)**
- *Architecture*: extend `app/artifacts.py` with `write_survey_package()`:
  variable specification sheet (data dictionary + provenance + constraints
  rationale), enumerator reference guide (per-question: label, hint, skip
  narrative from `logic_flow`, constraints in plain words), data collection
  plan skeleton (sections, duration estimate from D8, device requirements).
- *Outputs*: `enumerator_guide.md`/`.pdf`, `variable_spec.xlsx`,
  `collection_plan.md` in the output package.
- *Tests*: golden-file style content assertions per artifact.
- *Acceptance*: package builds offline for any valid form with no AI enabled.

**4. A9 — Enumerator instruction generator (S)**
- *Architecture*: new `ai/enumerator_notes.py`, advisory suggestions
  (reuses `AISuggestion` with kind `hint`), applied via the existing
  accept/reject panel into the `hint` column (never overwriting an
  author-supplied hint — same co-share contract as translation).
- *Acceptance*: accepted notes land in `hint`; author hints never overwritten.

### Tier 2 — high impact, larger effort

**5. D1 — Reverse engineering engine (L)**
- *Architecture*: new `parsers/xlsform_reader.py` (XLSForm .xlsx →
  `Questionnaire`, inverse of the exporter — reuse the dialect maps) + new
  `docgen/` package rendering: enumerator questionnaire (DOCX via
  `python-docx`, already a dependency for parsing), survey specification
  (Markdown/PDF via the existing fitz path), logic narrative (from
  `logic_flow`), data dictionary (exists).
- *Interface*: `xlsform-architect reverse form.xlsx --out docs/` CLI verb;
  `XLSFormReader.read(path) -> Questionnaire`.
- *Tests*: round-trip (export → read → export byte-comparable rows);
  golden-file doc rendering.
- *Acceptance*: any form the tool exports can be read back losslessly;
  third-party XLSForms read with assumptions logged for unsupported columns.
- *Note*: the reader also unlocks D3 diffs directly between .xlsx versions.

**6. D7 — Domain rule packs (L, content-heavy)**
- *Architecture*: `knowledge/packs/<domain>.yaml` using the existing rule
  schema (type keywords, constraint templates, choice lists, calculations);
  loader gains `KnowledgeBase.load(packs=["nutrition"])` and CLI `--packs`.
  Nutrition first (MUAC 65–350mm, WHZ plausibility, IYCF age windows,
  SMART/IMAM/OTP/TSFP vocabularies), then health (DHIS2/HMIS naming),
  agriculture, education, humanitarian (PDM, rapid assessment).
- *Tests*: per-pack fixture questionnaires asserting pack rules fire and
  domain-neutral behaviour is unchanged when no pack is loaded.
- *Acceptance*: `--packs nutrition` constrains a MUAC question that the
  neutral rules leave open; no pack = current behaviour byte-for-byte.
- *Note*: packs are pure YAML — community-editable without touching Python.

**7. A5 + H2 — Objective coverage review & matrix (M)**
- *Architecture*: new `ai/coverage.py`; user supplies objectives/indicators
  (UI textarea, CLI `--objectives file`); rules build the question inventory
  (deterministic), AI maps objectives ↔ questions and marks gaps. One call.
- *Outputs*: coverage matrix artifact (`coverage_matrix.md`) + advisory findings.
- *Acceptance*: an objective with no mapped question is flagged; mappings
  cite question names that exist (validated deterministically).

**8. A4 — Missing question detection (S)**
- *Architecture*: new `ai/completeness.py`; sends question inventory +
  survey context; returns "potentially missing items" as advisory findings
  (category `ai_review`). Never mutates the form.
- *Acceptance*: weight+MUAC-without-height fixture yields a height suggestion;
  suggestions never appear as form rows.

### Tier 3 — valuable, lower urgency

**9. A2 — Enumerator experience review (S)**: second persona prompt in the
quality reviewer (transitions, probing burden, instruction clarity);
advisory findings only.
**10. A1 — Methodology review completion (S)**: extend the reviewer's brief
with sequencing/ordering critique; merges with A2 into one "expert panel"
call to keep the one-call-per-form budget.
**11. A14 — Semantic logic review (S)**: feed the `logic_flow` graph to the
model for conceptual-pathway review (D5 already owns everything decidable).
**12. A8 — Indicator mapping engine (M)**: infer indicators from questions;
emit indicator matrix + means-of-verification artifact; advisory.
**13. A11 — Domain plausibility review (S, after D7)**: pack vocabulary +
survey context grounds a domain-completeness prompt.
**14. H3 — Smart assumption log completion (S)**: run the finding-explainer
pattern over assumption-log entries (batched, one call).
**15. D2 extensions (S)**: Mermaid export, SVG/PNG rendering (needs optional
`graphviz` binary — keep optional), choice-filter/constraint edges as
dashed overlays.

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
