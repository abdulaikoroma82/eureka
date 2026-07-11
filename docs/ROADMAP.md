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
| A1 | Methodology Expert Review | ✅ | `ai/quality_reviewer.py` (expert-panel category 5: sequencing, priming, sensitive-question placement) |
| D7 | Domain Rule Packs | ✅ | `knowledge/packs/*.yaml` (nutrition, health, agriculture, education, humanitarian) + `KnowledgeBase.load(packs=...)`, CLI `--packs`, UI multiselect |
| A4 | Missing Question Detection | ✅ | `ai/completeness.py` (advisory findings; never adds questions) |
| A5 | Objective Coverage Review | ✅ | `ai/coverage.py` (objectives via UI textarea / `--ai-objectives`) |
| H2 | Coverage Matrix | ✅ | `coverage_matrix.md` artifact + Quality tab; question refs verified deterministically |
| A2 | Enumerator Experience Review | ✅ | `ai/quality_reviewer.py` (expert-panel category 4: transitions, probing burden, recording pitfalls) |
| A8 | Indicator Mapping Engine | ✅ | `ai/indicators.py` → `indicator_matrix.md` + Quality tab; question refs verified deterministically |
| A14 | Semantic Logic Review | ✅ | D5 owns decidable defects; `ai/quality_reviewer.py` category 5 reviews conceptual pathways |
| D1 | Reverse Engineering Engine | ✅ | `parsers/excel_parser.py` reads XLSForms (incl. SurveyCTO dialect); importing one regenerates the full documentation package; printable `*_survey_instrument.docx` in every package |
| A11 | Domain Plausibility Review | 🟡 | survey-context grounding + domain packs + completeness review cover most of it; pack-vocabulary-aware design checks pending |
| H3 | Smart Assumption Log (completion) | 🟡 | rules record everything; AI explains findings but not yet assumption entries |
| D2 | Visual mapper extensions | 🟡 | Mermaid export shipped (embedded in logic_map.md); SVG/PNG needs the optional graphviz binary — deferred |

---

## Remaining work

Everything else from the review is shipped (see the table). Three partial
items remain, all small:

* **A11 — pack-aware domain plausibility (S)**: feed the loaded pack's
  vocabulary into the completeness/review prompts so domain checks cite the
  pack's own concepts (e.g. "an IMAM survey usually records oedema").
* **H3 — assumption-log explanations (S)**: run the finding-explainer
  pattern over assumption-log entries (batched, one API call) so each
  logged decision carries a plain-language elaboration.
* **D2 — SVG/PNG rendering (S)**: shell out to the `graphviz` binary when
  (and only when) it is installed; the DOT and Mermaid sources already
  ship, so this is a convenience export.

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
