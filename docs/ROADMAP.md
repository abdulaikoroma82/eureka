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
| H5 | Readiness Assessment | ✅ | D10 findings narrated operationally by `ai/narrative.py` |
| D6 | Metadata & Documentation Generator | ✅ | `app/artifacts.py`: enumerator guide, variable specification, collection plan |
| A9 | Enumerator Instruction Generator | ✅ | `ai/enumerator_notes.py` (advisory `hint` suggestions; author hints win) |
| D10 | Deployment Readiness Checks | ✅ | `validation/readiness_validator.py` (translation/media/device/metadata completeness) + platform matrix + pyxform deep check |
| A1 | Methodology Expert Review | 🟡 | overlaps quality reviewer; senior-methodologist persona + sequencing review pending |
| A2 | Enumerator Experience Review | ⬜ | pending |
| A4 | Missing Question Detection | ⬜ | pending |
| A5 | Objective Coverage Review | ⬜ | pending |
| A8 | Indicator Mapping Engine | ⬜ | pending |
| A11 | Domain Plausibility Review | 🟡 | survey-context grounding exists (constraints/review); domain-specific design checks pending |
| A14 | Semantic Logic Review | 🟡 | D5 catches decidable defects; AI review of *conceptual* pathways pending |
| D1 | Reverse Engineering Engine | ⬜ | pending |
| D7 | Domain Rule Packs | ⬜ | pending (loader already supports custom rule dirs via `--rules`) |
| H2 | Coverage Matrix | ⬜ | pending (depends on A5) |

---

## Recommended implementation order (pending items)

Ranked by impact ÷ effort. Effort scale: **S** ≤ 1 day · **M** ≤ 3 days ·
**L** ≤ 2 weeks.

### Tier 1 — high impact, small/medium effort — ✅ ALL SHIPPED

D10 (readiness validator), H5 (readiness narration), D6 (implementation
package: enumerator guide, variable specification, collection plan), and
A9 (enumerator instruction suggestions) are implemented — see the status
table above for locations.

### Tier 2 — high impact, larger effort

**1. D1 — Reverse engineering engine (L)**
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

**2. D7 — Domain rule packs (L, content-heavy)**
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

**3. A5 + H2 — Objective coverage review & matrix (M)**
- *Architecture*: new `ai/coverage.py`; user supplies objectives/indicators
  (UI textarea, CLI `--objectives file`); rules build the question inventory
  (deterministic), AI maps objectives ↔ questions and marks gaps. One call.
- *Outputs*: coverage matrix artifact (`coverage_matrix.md`) + advisory findings.
- *Acceptance*: an objective with no mapped question is flagged; mappings
  cite question names that exist (validated deterministically).

**4. A4 — Missing question detection (S)**
- *Architecture*: new `ai/completeness.py`; sends question inventory +
  survey context; returns "potentially missing items" as advisory findings
  (category `ai_review`). Never mutates the form.
- *Acceptance*: weight+MUAC-without-height fixture yields a height suggestion;
  suggestions never appear as form rows.

### Tier 3 — valuable, lower urgency

**5. A2 — Enumerator experience review (S)**: second persona prompt in the
quality reviewer (transitions, probing burden, instruction clarity);
advisory findings only.
**6. A1 — Methodology review completion (S)**: extend the reviewer's brief
with sequencing/ordering critique; merges with A2 into one "expert panel"
call to keep the one-call-per-form budget.
**7. A14 — Semantic logic review (S)**: feed the `logic_flow` graph to the
model for conceptual-pathway review (D5 already owns everything decidable).
**8. A8 — Indicator mapping engine (M)**: infer indicators from questions;
emit indicator matrix + means-of-verification artifact; advisory.
**9. A11 — Domain plausibility review (S, after D7)**: pack vocabulary +
survey context grounds a domain-completeness prompt.
**10. H3 — Smart assumption log completion (S)**: run the finding-explainer
pattern over assumption-log entries (batched, one call).
**11. D2 extensions (S)**: Mermaid export, SVG/PNG rendering (needs optional
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
