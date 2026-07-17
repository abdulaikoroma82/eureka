[← Documentation index](../README.md#documentation)

# Architecture

## Architecture

Structurally, XLSForm Studio is an **AI-first compiler with deterministic
guardrails**: a parser turns a source questionnaire into an intermediate
representation and lays out the platform scaffold, the AI author drafts every
field into that scaffold, and deterministic rules then enforce standards and
validate against the XLSForm specification before an exporter emits the target
artefacts (the XLSForm workbook plus its supporting documentation).

```
              User Interface  (Streamlit UI  /  CLI)
                      |
              Application Controller  (app/workflow.py)
                      |
      ---------------------------------------------
      |                  |                        |
   Parser           AI Author               Validator
 (parsers/)     (ai/form_author.py)        (validation/)
   scaffold      drafts every field       enforces standards
      |                  |                        |
      ---------------------------------------------
                      |
           Standards enforcement  (engine/)  — rules keep the AI on-standard
                      |
              XLSForm Generator  (xlsform/)
                      |
                Output Package
   (XLSForm · data dictionary · QA report · assumption
    log · logic map · version history)
```

All stages communicate through one intermediate representation
(`xlsform_studio/models.py`): a `Questionnaire` of `Question`, `Choice` and
`ChoiceList` objects. A parser only has to produce a raw `Questionnaire`; the
AI author then fills every XLSForm field and everything downstream works
unchanged. The `ai/` package is the **only** part of the codebase that makes a
network call; because authoring is AI-first, a run requires a `DEEPSEEK_API_KEY`.
The legacy fully-deterministic compiler (`engine/rule_engine.py`) remains as an
internal standards/test seam (`authoring="deterministic"` / `XLSFS_AUTHORING`),
never selected by the UI or CLI.

### Project layout

```
xlsform_studio/
├── app/            # controller, config, CLI (main.py) and Streamlit UI (ui.py)
├── parsers/        # DOCX / XLSX / PDF / CSV / JSON / text parsers
├── engine/         # standards enforcer + legacy deterministic compiler (seam)
├── ai/             # AI author (form_author.py) + enrichment layer (DeepSeek)
├── xlsform/        # survey / choices / settings builders + exporter
├── validation/     # structure / logic / deployment validators + report
├── knowledge/      # editable YAML rule packs
├── examples/       # sample questionnaires
├── output/         # generated packages land here
└── tests/          # pytest suite
```

---

## Reviewing the AI draft

The tool optimises for **transparent assistance, not blind trust**: the AI
drafts the whole form, but authoring at the boundary between natural-language
questionnaires and precise XLSForm/XPath semantics will sometimes be wrong,
so every authored field stays visible and editable before you export.

Four of the authored fields — **type**, **choice list**, **relevance**,
**constraint** — also carry a structured confidence so genuine ambiguity
surfaces first:

| Confidence | Meaning |
| --- | --- |
| 🟢 High | An exact, unambiguous choice (a clear type, an explicit Yes/No pair). |
| 🟡 Medium | A reasonable reading that could be wrong (a compiled skip condition, a plausible constraint bound). |
| 🔴 Low | A generic fallback with no real signal — or nothing could be settled at all. |

**Conservative compilation.** When something is too ambiguous to settle
safely — an unparseable compound condition, a "skip to question N" jump
XLSForm has no construct for — the tool does **not** emit a
plausible-but-possibly-wrong expression. It leaves the field blank, records
it as a low-confidence decision, and surfaces it for a human instead.

**The review panel.** In the Streamlit app, a "🧐 Review the AI draft" panel
appears before the download buttons — grouped one expander per question, with
any question that has an unsettled field expanded automatically. **Every
authored field is editable inline** (name, type, choice list, label, hint,
required, relevance, constraint + message, calculation, choice filter,
appearance, default), each shown with the AI's confidence and reason. Change
anything and apply — only changed fields are written, and the XLSForm is
rebuilt and re-validated from your reviewed version. Renaming a variable
rewrites every `${...}` reference to it automatically. In the CLI, the same
information prints as a summary (fields needing input are listed explicitly;
the rest are in `assumptions_to_verify.md`) — batch/CI runs are
non-interactive by design, so the CLI never blocks or guesses on your behalf.

Every human edit is recorded as a fresh, high-confidence "reviewed by a
human" decision, so a later export shows the review happened.

---

---

## Output package

Each run writes a timestamped folder under `output/` containing:

1. `*.xlsx` — the XLSForm (survey / choices / settings sheets)
2. `*_data_dictionary.xlsx` — every variable, type, choices, constraint, calculation
3. `QA_Report.pdf` — the validation report, including the **Form Quality
   Index** (0–100 across seven categories: naming, constraint coverage,
   logic completeness, choice consistency, validation readiness,
   documentation, reusability), a deterministic **interview-duration /
   respondent-burden estimate**, and **deployment-readiness findings**
   (translation completeness per language, media file manifest, device
   fit for long choice lists)
4. `assumption_log.md` — every deterministic decision made
5. `assumptions_to_verify.md` — the same decisions reorganised into a
   prioritized review checklist: **Critical** (logic resolutions,
   constraint bounds, ambiguous classifications, AI-applied changes —
   each with a checkbox and a concrete "what to verify" action),
   **Advisory** (translations, merges, unapplied AI suggestions), and
   **Informational** (routine bookkeeping) — clear the critical items
   before deployment
6. `logic_map.md` — relevance / constraint / calculation relationships,
   including an ASCII skip-pattern flowchart:

   ```text
   resident — Are you a resident of this district?
   ├── Yes → years_lived
   └── otherwise → respondent_age
   ```
7. `logic_flow.dot` — the same flowchart as a Graphviz graph (only written
   when the form has skip logic); the app's **Logic map** tab renders it
   interactively, with answer codes shown as their labels
8. `enumerator_guide.md` — a field-ready, question-by-question reference:
   how to record each answer, the options, skip rules in plain words
   ("Ask only when resident = Yes"), and valid-answer rules
9. `*_variable_specification.xlsx` — the data dictionary plus provenance:
   every engine assumption logged per variable, for data managers
10. `collection_plan.md` — a data-collection plan skeleton: instrument
   overview, time per section, interviews-per-enumerator planning figure,
   device requirements (GPS/camera/media files), languages, and a
   checklist of what to complete manually
11. `*_survey_instrument.docx` — a printable paper questionnaire: sections
    as headings, numbered questions, tick-boxes for options, answer lines,
    and skip rules in plain words — a paper backup and a review copy for
    non-technical stakeholders
12. `version_history.json` — append-only audit trail across runs
13. `change_report.md` — only with `--diff-against OLD_FILE`: what changed
   versus a previous questionnaire version (added/removed/renamed
   variables, logic/constraint changes, choice-list edits), with breaking
   changes for longitudinal analysis flagged explicitly
14. `coverage_matrix.md` — only with the `coverage` AI feature enabled: maps
   your stated study objectives to the questions that inform each one and
   flags gaps, also shown in the app's Quality tab; every cited question
   name is verified to exist before it's written
15. `indicator_matrix.md` — only with the `indicators` AI feature enabled: a
   draft M&E reporting framework (indicator, source questions, aggregation
   level, means of verification), also shown in the Quality tab; source
   question references are likewise verified to exist
16. `*_model.json` — the **provenance sidecar**: the complete internal model,
   including every field's confidence and the assumptions behind it. This is
   what the workbook itself can't carry, and it's what makes round-trip
   editing possible (see below). Written on every run.
17. `survey_design_report.md` — the **Survey Design Score**: a deterministic
   methodological assessment across ten dimensions (question order, recall
   consistency, measurement validity, …), with a per-dimension breakdown and
   the specific findings behind each deduction. Written on every run.

Every document above is authored **deterministically** and owns every fact
(variable names, types, logic, counts, checklist tiers) — the same form
always produces the same documents, byte-for-byte, with no model in the loop.

---

### Reverse engineering an existing XLSForm

The pipeline runs in both directions: feed a **deployed XLSForm** (`.xlsx`
with `survey`/`choices`/`settings` sheets — SurveyCTO's dialect headers are
understood too) as the input, and the full documentation package above is
regenerated from it: printable questionnaire, enumerator guide, data
dictionary, logic map and flowchart, quality score, QA report. Useful for
inheriting an undocumented form or producing stakeholder-readable copies.

```bash
python -m xlsform_studio.app.main deployed_form.xlsx
```

---

### Round-trip editing (edit the XLSForm, keep the provenance)

Reverse engineering regenerates docs from *any* XLSForm, but a plain
re-import starts from zero — the workbook has no column for "how sure was the
tool about this field, and why," so that provenance is lost. **Round-trip
editing** fixes that: export a form, edit the `.xlsx` in Excel or a
platform's form builder, and re-import it *against the run that produced it*,
keeping the confidence and assumptions for everything you didn't touch.

Every run writes a **provenance sidecar** (`*_model.json`) — the complete
internal model, decisions and all. Re-import an edited workbook by pointing
`--from-model` at that sidecar:

```bash
python -m xlsform_studio.app.main household_edited.xlsx \
    --from-model output/household_20260101_090000/household_model.json
```

The edited form is parsed deterministically — **never re-drafted by AI** —
and reconciled field by field against the snapshot:

* a field you **didn't change** keeps its original confidence and reason;
* a field you **did change** becomes a fresh, high-confidence *"reviewed by a
  human"* decision — exactly how an edit made in the in-app review panel is
  recorded, so an edit in Excel and an edit in the UI are indistinguishable
  downstream;
* a **renamed** variable (new `name`, same label) is recognised as a rename,
  not a delete-plus-add, so its confidence and assumptions carry over to the
  new name — though, unlike an in-app rename, round-trip takes the workbook
  literally and does **not** auto-rewrite `${old}` references: if you renamed a
  variable but left a reference dangling, the validator flags it honestly;
* a **new** question is flagged low-confidence for review, and a **removed**
  one is logged.

The full documentation package (and a refreshed sidecar) is then rebuilt from
the merged model. Because nothing is authored, round-trip re-import needs **no
API key**.

You can do this two ways:

* **In the app** — sidebar section **5 · ♻️ Re-import an edited XLSForm**:
  drop in the edited `.xlsx` and its `*_model.json`, click **Re-import &
  rebuild**, and the reconciled form flows into the same review panel, tabs
  and downloads as a fresh run.
* **In library code** —
  `Workflow().run_roundtrip(edited_path, model_json_path)`.

This is what makes XLSForm Studio a *canonical editor* for a form, not just a
one-shot generator.

---
