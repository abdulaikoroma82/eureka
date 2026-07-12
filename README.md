# XLSForm Studio

**XLSForm Studio is an AI-first survey engineering platform that drafts,
validates, documents, and quality-assures questionnaires for the entire XLSForm
ecosystem.**

XLSForm Studio lets a survey designer, M&E officer or researcher drop in a
questionnaire of **any kind** (Word, Excel, PDF, CSV or JSON) and get back a
complete, validated XLSForm package — the spreadsheet plus a data dictionary,
QA report, assumption log, logic map and version history. It applies the
**standard rules of the XLSForm specification**; it is not tied to any
particular survey domain.

> **AI drafts the form; deterministic rules keep it on-standard.** The model
> (DeepSeek) interprets the questionnaire and authors every field — types,
> machine names, labels, hints, relevance/skip logic, constraints,
> calculations and choice lists. Deterministic rules bracket the AI on both
> sides: the parser lays out the platform scaffold (sheets and columns), and
> the standards enforcer plus validators check the draft against the XLSForm
> specification and the target platform's rules. You then **review and edit
> the AI draft** before download.
>
> **AI is essential, not optional.** A run requires a configured DeepSeek API
> key (`DEEPSEEK_API_KEY`); there is no offline authoring fallback. See
> [AI authoring & enrichment](#ai-authoring--enrichment) for the optional
> enrichment passes (translation, quality review, narrative, document
> co-writing) that refine the draft and its documentation.

> 🟢 **New to this / non-technical?** Start with the plain-language
> [Getting Started guide](docs/GETTING_STARTED.md) — no coding needed.

---

## Why it exists

Hand-coding XLSForms is slow and error-prone: mistyped variable names, broken
`relevant` references, missing choice lists, inconsistent constraints. XLSForm
Studio standardises that work and catches the errors before deployment.

---

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

## Installation

Requires **Python 3.11+** (3.12+ recommended).

```bash
git clone <repo-url>
cd eureka
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Or install as a package (gives you the `xlsform-studio` command):

```bash
pip install -e .
```

---

## Usage

### 1. Graphical app (Streamlit)

```bash
python run_ui.py
# or:  streamlit run xlsform_studio/app/ui.py
```

Then in the browser: upload a questionnaire → pick a target (Kobo, SurveyCTO,
ODK, Ona, CommCare) → click **Generate XLSForm**. Live processing steps are
shown, followed by the validation result and download buttons for the XLSForm
and the full `.zip` package.

### 2. Command line

```bash
python -m xlsform_studio.app.main xlsform_studio/examples/event_registration.json
python -m xlsform_studio.app.main survey.docx --title "Household Survey" --output ./out
# target a platform: validates against ITS standards and writes ITS dialect
python -m xlsform_studio.app.main survey.docx --target surveycto
# use a customised ruleset instead of the bundled standard rules
python -m xlsform_studio.app.main survey.docx --rules ./my_rules
# after `pip install -e .`
xlsform-studio design.csv --target kobo
# step through an interactive interview simulation in the terminal
xlsform-studio survey.docx --simulate

# optional AI assist (requires DEEPSEEK_API_KEY) — see the AI section below
python -m xlsform_studio.app.main survey.docx --ai
python -m xlsform_studio.app.main survey.docx --ai \
    --ai-features translate,review --ai-languages "French:fr,Spanish:es"
# ground AI suggestions in your survey's domain
python -m xlsform_studio.app.main survey.docx --ai \
    --ai-context "child nutrition survey in rural districts"
# or use the standalone shortcuts (each implies --ai with that feature)
python -m xlsform_studio.app.main survey.docx --ai-review --ai-explain \
    --ai-group --ai-rewrite --ai-order --ai-name --ai-cross
```

The process exits non-zero if validation finds blocking errors, so it slots
into CI / batch pipelines.

### 3. As a library

```python
from xlsform_studio.app.workflow import Workflow

result = Workflow().run_from_dict({
    "settings": {"form_title": "Event Registration"},
    "survey": [
        {"question": "Are you attending the event?",
         "choices": ["Yes", "No"], "required": True},
        {"question": "Preferred session date", "logic": "ask if yes"},
        {"question": "Number of guests"},
    ],
})

print(result.report.summary())         # validation summary
print(result.outputs["xlsform"])       # path to the .xlsx
```

---

## Input formats

| Format | How it is read |
| --- | --- |
| **JSON** | Structured form definition (see below). Exact, no guessing. |
| **XLSX** | Either an existing XLSForm (survey/choices/settings sheets) *or* a one-row-per-question design grid. Auto-detected. |
| **CSV**  | Design grid — columns `question, type, choices, required, section, logic, …` |
| **DOCX** | Word questionnaire; paragraphs and tables are extracted and structured. |
| **PDF**  | Text-based PDF questionnaire. |
| **TXT/MD** | Plain-text questionnaire. |

### JSON input schema

```json
{
  "settings": { "form_title": "My Form", "form_id": "my_form", "version": "1" },
  "survey": [
    {
      "question": "Are you a registered member?",
      "type": "select_one",              // optional — inferred if omitted
      "choices": ["Yes", "No"],          // optional
      "required": true,                  // optional
      "logic": "ask membership date if yes",  // natural language → relevant
      "section": "Registration"          // optional grouping
    }
  ]
}
```

Only `question` is mandatory. The AI author fills in the type, variable
name, choice list, relevance, constraint and any derived calculations; the
deterministic rules then enforce standards and validate the result.

---

## What the deterministic layer does

In the AI-first pipeline the model authors every field; the deterministic
layer brackets it — the parser lays out the **scaffold** and its structural
intelligence, the rules encode the **standards** the draft must meet, and the
validators **verify** it. That same deterministic engine also remains a
complete offline compiler, reachable as an internal standards/test seam
(`authoring="deterministic"`), and it is what powers the checks below. These
are the standards and structural transforms the deterministic layer owns:

| Module | Behaviour | Example |
| --- | --- | --- |
| **Classifier** | Assigns XLSForm types | `Yes/No → select_one yes_no`, `age → integer`, `amount → decimal`, `GPS → geopoint`, `photo → image` |
| **Variable namer** | Safe, unique names | `"Preferred contact method" → preferred_contact_method` |
| **Logic engine** | Natural language → expressions: compound conditions, negation, ranges, numbered references, choice shorthand | `"if yes and age over 18"`, `"unless married" → not(...)`, `"between 18 and 65" → >=18 and <=65`, `"if question 4 is married"` (resolves the source numbering, incl. coded options → stored codes), bare `"if married"` when unambiguous; multi-selects use `selected(...)` |
| **Constraint engine** | Validation ranges | `age → . >= 0 and . <= 120`, `% → . >= 0 and . <= 100`, `date → . <= today()` |
| **Calculation engine** | Derived fields | age in years from a date of birth |

And structural intelligence on top:

* **Matrix / grid questions** — a Word table with items down the side and a
  rating scale across the top becomes one `select_one` per row, all sharing a
  single choice list.
* **Repeat groups (rosters)** — a heading like `FOR EACH HOUSEHOLD MEMBER`
  (or `"repeat": true` in JSON, or a `repeat` column in the design grid)
  wraps its questions in `begin repeat`/`end repeat`. Explicit
  `begin/end repeat` rows in JSON or an imported XLSForm pass through intact.
* **"Other (specify)"** — a select offering an Other option automatically
  gains a text follow-up shown only when Other is chosen.
* **Choice-list sharing** — identical option sets (e.g. a Likert scale used
  by ten questions) are merged into one list instead of duplicated.
* **Cascading selects & translations** — `choice_filter` and passthrough
  columns (`label::French (fr)`, media columns, cascade filter columns) are
  carried from structured inputs into the exported workbook.
* **PDF noise removal** — page numbers and repeated running headers/footers
  are stripped before parsing.
* **Skip-to patterns** — "skip to question 20" cannot be inverted safely, so
  it is surfaced as an explicit review note instead of a silent guess.

Every decision is recorded in the **assumption log** so it can be reviewed.

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

## The rule pack (editable, no code changes)

Platform profiles live in `xlsform_studio/knowledge/platforms.yaml`
(dialects, supported types, naming standards, per-platform tips). All other
standard rules live in `xlsform_studio/knowledge/xlsform_rules.yaml`:

* `type_keywords` — keyword → XLSForm type detection
* `yes_no` — the canonical shared Yes/No list and its detection tokens
* `constraints` / `type_constraints` — generic validation ranges and messages
* `calculations` — reusable standard calculate expressions
* `logic_tokens` — the natural-language vocabulary the logic engine understands
* `naming` — variable-naming rules (length, stopwords, abbreviations)

The bundled rules are **domain-neutral** — they encode standard XLSForm
behaviour that fits any questionnaire. To specialise the tool (e.g. add
domain-specific constraints or reusable choice lists), copy the file, edit it,
and point the tool at it with `--rules` on the CLI or
`KnowledgeBase.load(directory=...)` in code. The Python code never changes.

### Domain rule packs

Ready-made specialisations ship in `knowledge/packs/` — **nutrition**
(MUAC, weight/height, z-scores, IYCF), **health** (vitals, ANC, RMNCAH
counts), **agriculture** (land, livestock, yields), **education**
(enrolment, grades, assessment scores) and **humanitarian** (PDM, food
security, water access). Each pack adds type-detection keywords and
realistic value bounds *on top of* the neutral rules (pack rules match
first; with no pack, behaviour is unchanged byte-for-byte). They are plain
YAML — edit or add your own without touching Python.

```bash
python -m xlsform_studio.app.main survey.docx --packs nutrition,health
```

In the app: **"3 · Form details" → Domain rule packs**.

---

## AI authoring & enrichment

Authoring is **AI-first**: the model ([DeepSeek](https://api-docs.deepseek.com/))
drafts every field of the form, and deterministic rules enforce standards and
validate the result. This is essential — a run requires a `DEEPSEEK_API_KEY`
and there is no offline authoring fallback.

On top of authoring, a set of **optional enrichment passes** refine the AI
draft — translation into additional languages, a holistic quality/naming
review, a plain-English narrative of the validator's findings, and advisory
grouping/rewording suggestions. These stay off unless you enable them, and
they only ever annotate or refine the authored form, never re-author it.

| Feature | What it does | Why it can't be deterministic |
| --- | --- | --- |
| **Translation** | Generates `label::French (fr)`-style columns from your English labels — **only for labels you haven't already translated yourself**; finished translations are cached locally (`.translation_cache.json`) so regenerating a form doesn't re-pay for unchanged text | Translation is language generation, not pattern matching |
| **Cross-field constraints** | Suggests constraints that depend on another question, e.g. "end date must be on/after start date" — **combined with `and`** if the field already has an authored constraint | A per-question check only ever looks at one question at a time — it structurally cannot see the relationship between two |
| **AI quality review** | A holistic second pass flagging things structural checks can't see — semantic contradictions, unclear names, and respondent-experience traps (ambiguous phrasing, contradictory option lists, redundant questions, incoherent skip chains); advisory only | Requires reasoning across multiple fields' relationship to each other |
| **Explain findings** | Adds a one-sentence plain-English explanation to the validator's own findings, after validation runs | Rules own every fact (level, category, message); AI only makes them easier to read |
| **Quality narrative** | Writes the QA report's executive summary from the deterministic Form Quality Index, duration estimate, readiness findings and finding counts — it is sent only the audited metrics, never asked to re-judge the form | Turning seven scores and a risk rating into two readable sentences is prose generation; the numbers themselves stay 100% rules |
| **Document co-writing** | Rewrites the *framing prose* of the supporting documents (enumerator guide, collection plan, logic map, printable instrument, assumptions checklist) in better natural language, slotted under a labelled "AI-written" block; the deterministic builders still author every fact and render unchanged when it's off | Polishing an orientation paragraph is prose; the counts, names, logic and checklist tiers it frames stay 100% rules |
| **Missing-question detection** | Infers the survey's purpose and flags questions it probably needs but lacks (weight + MUAC with no height blocks weight-for-height) — advisory findings only, the tool **never adds questions** | Recognising that a set of questions implies an absent member is domain reasoning, not pattern matching |
| **Objective coverage matrix** | You list your study objectives; it maps each to the questions that inform it and flags gaps (`coverage_matrix.md` + Quality tab). Every cited question name is verified to exist — invalid references are discarded | Judging that two questions together measure "access to safe water" is semantics; the question inventory and reference checks stay 100% rules |
| **Indicator matrix** | Drafts an M&E reporting framework from the compiled questions: indicator, source questions (verified to exist), aggregation level, means of verification (`indicator_matrix.md`) | Which questions feed which indicator is meaning, not matching |
| **Question grouping** *(suggestion-only)* | Proposes logical sections for a form whose source document didn't provide them | "Water source" and "latrine type" belonging together is a semantic judgement |
| **Question rewording** *(suggestion-only)* | Flags ambiguous, double-barreled, leading or jargon-heavy questions and suggests clearer wording (or a split, which you apply in the source document) | Whether a sentence is leading is a language judgement |
| **Choice-list ordering** *(suggestion-only)* | Proposes a more logical option order — common answers first, themes adjacent, "Other"/"Refused" last | "Farming" belonging next to "Fishing" isn't a sortable property |
| **Variable-name suggestions** *(suggestion-only)* | Offers a more natural name where the deterministic one reads awkwardly; accepting a rename also rewrites every `${...}` reference to it | Judging what an analyst will find readable is a language call |
| **Enumerator instructions** *(suggestion-only)* | Drafts per-question field guidance (probing technique, common misunderstandings) as device `hint` text — only for questions with no author-written hint, which always wins | Anticipating how respondents misunderstand a question is survey-methodology judgement |

The five **suggestion-only** features never touch the form by themselves:
each produces an original-vs-suggested pair you accept or reject (in the
app's *AI suggestions* panel, which rebuilds and re-validates the workbook
with your accepted changes; on the CLI they are printed for manual review).
Every acceptance is re-validated at apply time and logged to the assumption
log.

### Where rules and AI genuinely co-share the same output

Three of the features above aren't a handoff ("rules tried, AI took over") —
they're true co-authorship of a single value, with a strict division of
authority:

* **Translation**: your supplied text always wins; AI only fills gaps, and
  skips the API call entirely for a language you already fully translated.
* **Cross-field constraints**: a field's final constraint can be the
  combination of the rule engine's single-field rule *and* AI's cross-field
  rule, e.g. `(. <= today()) and (. >= ${start_date})` — neither
  contribution is discarded.
* **Explain findings**: the finding itself (is it an error? what's wrong?)
  is 100% rules, always; AI only ever adds an `explanation` string beside
  it. Turn AI off and every finding is exactly as valid and exactly as
  severe — just less elaborated.

### What stays deterministic on purpose

Not everything that *could* be done with AI *should* be. Two things were
deliberately kept out of AI's hands even though a model could technically
improve them slightly:

* **Variable naming.** Naming needs to be free, instant, and — critically —
  **stable**: the same question must always produce the same variable name
  across re-runs, or version history and diffs become meaningless. The
  deterministic name is therefore always the one in use; the optional
  `naming` feature only ever *stores a suggestion* for you to accept, and
  an accepted rename deterministically rewrites every `${...}` reference so
  nothing dangles.
* **All structural / type / deployment validation.** These checks are
  enumerable, must be exactly right, and run on every question in every form
  — exactly what rule engines are for. The AI author drafts each question's
  single-field constraint as part of authoring the form; the deterministic
  validators then verify it. AI *enrichment* only adds what a per-question
  check structurally cannot reach: the *cross-field* case — a constraint that
  depends on another question's answer.

If a cross-field AI suggestion targets a question that already has a
constraint (very common — a date field is usually authored with a "not in
the future" rule already), the two are **combined with `and`**, not one
discarded — both constraints stay enforced.

### Setup

```bash
export DEEPSEEK_API_KEY="sk-..."          # https://platform.deepseek.com
python -m xlsform_studio.app.main survey.docx --ai
```

Or in the Streamlit app: expand **"4 · 🤖 AI assist"** in the sidebar, paste a
key (kept only for that browser session, never written to disk) or rely on
the environment variable, tick **Enable AI assist**, and choose which
features and languages you want.

### Safety and cost design

* **Bounded, batched calls.** Each feature makes at most **one API call per
  form** (translation makes one call per target *language*), regardless of
  how many questions the form has — not one call per question.
* **AI output is never trusted blindly.** Every suggestion is validated
  before being applied: skip-logic conditions must reference real question
  names or they are rejected; reclassifications must be a recognised XLSForm
  type or they are rejected; AI review findings are capped at `warning`
  severity and can never fail validation the way a real structural error
  does.
* **Everything is logged.** AI-applied changes are written to the assumption
  log with an explicit "AI-suggested... please review" note, and AI review
  findings appear in the QA report tagged `ai_review` so they're never
  confused with the deterministic checks.
* **Fails open, not closed.** If the API key is missing, the network is
  unreachable, or DeepSeek returns something unexpected, the affected
  feature is skipped with a clear note — the deterministic result is
  returned regardless, never blocked by an AI failure.

---

## Platform-specific standards

Choosing a target platform genuinely changes the output — the tool applies
**that platform's** rules, not just the generic XLSForm spec. The profiles
live in `xlsform_studio/knowledge/platforms.yaml` (editable, no code
changes — adding a platform is a YAML edit; the UI, CLI and compatibility
matrix pick it up automatically):

| Platform | Column dialect | Notable type support | Naming standards |
| --- | --- | --- | --- |
| **KoboToolbox** | standard | `range`, `rank`, `audit`, `background-audio`, … | ≤ 64 chars |
| **SurveyCTO** | `relevance`, `constraint message` (its template headers) | `text audit`, `audio audit`, `sensor_*`, `calculate_here`; rejects `range`/`rank`/`audit` | must start with a letter; ≤ 32 chars (Stata exports) |
| **ODK** | standard | full pyxform set incl. `osm` | ≤ 64 chars |
| **Ona** | standard | ODK set incl. `osm` (ODK-based platform) | ≤ 64 chars |
| **CommCare** | standard | core XLSForm set only — no `range`/`rank`/`geotrace`/`geoshape`/external selects | ≤ 64 chars |

The **compatibility matrix is honest per platform**: a form that uses `rank`
reports ✅ Kobo / ✅ ODK / ✅ Ona / ❌ SurveyCTO / ❌ CommCare, with the error
telling you which platforms *do* support the offending type.

### Coverage & the wider landscape

XLSForm Studio covers the **XLSForm family** of mobile data collection
platforms — KoboToolbox, SurveyCTO, ODK, Ona and CommCare — which all consume
the XLSForm format this tool produces (CommCare via its Form Builder import).
Platforms that use **entirely different form formats** — Survey Solutions
(World Bank), REDCap, CSPro, Epicollect5, Magpi, Fulcrum — are out of scope:
supporting them means building a separate exporter per format, not an
XLSForm variant.

---

## Validation & deployment compatibility

The validator runs in layers:

* **Structure** — survey/choices/settings present, every question typed and
  named, and `begin/end group` & `begin/end repeat` markers balanced.
* **Logic** — no duplicate names, no broken `${…}` references, no missing/empty
  choice lists, and **no dead comparisons**: `${sex}='femalee'` (a typo) or a
  value the referenced list can never hold is flagged, because it would
  deploy fine and simply never fire.
* **Expression syntax** — every `relevant` / `constraint` / `calculation` /
  `choice_filter` expression is parsed for structural validity: unbalanced
  parentheses or quotes, doubled or dangling operators (`. >< 5`), missing
  commas in function calls, malformed `${…}` references, and unknown XPath
  function names. This covers ground pyxform defers to the (Java-based) ODK
  Validate step, which this tool deliberately does not bundle.
* **Choice-list quality** — deterministic semantic checks on every list:
  recognised ordinal scales (Likert, satisfaction, frequency, quality)
  missing intermediate categories; options with a logical order (days,
  months, sizes, numeric ranges) listed out of order; an "Other" option
  with no specify follow-up question (an error — those answers are
  unrecoverable); non-sequential or outlier value coding (1, 2, 3, 99)
  flagged for confirmation. Reported under **Choice List Quality** in the
  QA report.
* **Static path analysis** — enumerates the possible enumerator paths
  implied by the form's `relevant` conditions (branching on referenced
  `select_one` answers, three-valued logic for conditions it can't
  decide) and verifies that every `calculation` / `constraint` /
  `choice_filter` reference actually holds a value on the paths where the
  expression runs. Catches: expressions over variables that are
  *definitely empty* on some path (skipped group/repeat — an error that
  every static check misses but the device won't), questions unreachable
  under contradictory conditions, references into a repeat from outside
  it (repeat variables are scoped), required questions whose `relevant`
  can skip them, and near-dead questions reachable on under 5% of paths.
  Beyond 10,000 paths it switches to a conservative approximation (noted
  in the report) that may over-warn but cannot miss the errors. Reported
  under **Path Analysis** in the QA report; disable with
  `--no-path-analysis`.
* **Deployment** — valid ODK/XML identifiers, no reserved words, recognised
  types and appearances.
* **Platform** — the chosen target's own standards (types, naming, settings)
  from `platforms.yaml`, as described above.
* **Deep check (pyxform)** — the tool then runs **pyxform**, the same engine
  KoboToolbox and ODK use, to convert the form to an ODK XForm **offline**. If
  that succeeds, the form is compatible with the ODK/Kobo toolchain at a
  near-authoritative level; if pyxform rejects it (e.g. an unresolved
  reference or a broken group), the form is marked incompatible on every
  platform. This runs automatically when `pyxform` is installed and can be
  turned off with `Validator(deep=False)`.

> The one thing this does **not** do is run ODK Validate (the Java step that
> checks full XForm runtime semantics). The expression-syntax layer above now
> covers the most common class of what Validate catches (malformed
> expressions), but every platform still runs its own validation when you
> upload — treat that as the final authoritative check.

### Confidence levels

A "warning" and a "confirmed" fact are not the same kind of claim, so every
finding is also tagged with **how sure the tool is**, independent of its
error/warning/info severity:

| Icon | Confidence | Meaning |
| --- | --- | --- |
| ✅ | **Confirmed** | Verified by an actual platform toolchain — pyxform converted the form to a real ODK XForm, or refused to. |
| 🔎 | **Checked** | This tool's own deterministic rule or grammar checked it exactly (structure, logic, references, expression syntax, path analysis). |
| 🧭 | **Heuristic** | A pattern-matched inference or AI suggestion about likely intent — useful, but not a proof. Review it. |
| ❔ | **Unsupported** | The tool could not check this (an unrecognised function, deep validation unavailable or incomplete) and passed it through unchanged rather than guessing or rejecting it. |

The principle: **never reject or silently accept something this tool
genuinely can't verify — say so.** An unrecognised XPath function in a
`choice_filter` is a warning tagged ❔ *unsupported*, not a hard error and
not a silent pass; a pyxform conversion failure is an error tagged ✅
*confirmed*, because that came from the real toolchain, not a guess. The
CLI, the Streamlit Findings tab, and the Markdown/PDF QA report all show
the confidence icon next to every finding.

Results are written to `QA_Report.pdf` in the output package.

---

## Interview simulation

Static checks tell you the form is *well-formed*; the simulator tells you it
*behaves*. Instead of deploying to a device and tracing skip logic by hand,
you answer the form right here and watch its logic run:

* **Skips** — every `relevant` is re-evaluated against your answers so far,
  hiding and revealing questions live (and logging what got skipped and
  why).
* **Constraints** — checked the moment you submit, with `.` bound to your
  candidate answer; a violation is rejected with its `constraint_message`
  instead of being recorded.
* **Calculations** — `calculate` fields recompute as their inputs change,
  shown running in a live panel.
* **Repeats** — a roster can be instantiated as many times as you like, each
  instance with its own answers and its own scope (nested repeats included).

**In the web app:** open the **🎬 Simulate** tab after generating a form,
answer with real widgets, and watch the live side panel (answered, skipped,
calculations, recent activity).

**In the terminal:**

```bash
xlsform-studio survey.docx --simulate
```

```text
Are you a resident? *
    1 = Yes
    0 = No
> 1
Years lived here *
> 999
  ✗ 0-120 only. — not recorded; answer again.
> 5
  = status=local
```

The simulator is a pure, deterministic engine — the same concrete expression
evaluator the validator trusts — so it never contacts a network and never
changes the form; it only *runs* it.

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

Every document above is authored **deterministically** and owns every fact
(variable names, types, logic, counts, checklist tiers). With the optional
`documents` AI feature enabled, the model additionally **co-writes the
framing prose** of the enumerator guide, collection plan, logic map,
printable instrument and assumptions checklist — slotted under a labelled
"AI-written" block, never replacing a fact. Turn it off and every document is
byte-for-byte the deterministic version.

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

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

The suite (`xlsform_studio/tests/`) covers the naming, classification,
logic, constraint and calculation engines, the builders/exporter, the
validators (including static path analysis and choice-list auditing), the
interview simulator, every parser, the end-to-end workflow, and the optional
AI layer (fully mocked at the network boundary — no API key or internet
connection is needed to run the suite).

---

## Packaging as a Windows application

See [`packaging/README.md`](packaging/README.md). In short:

```bat
pip install -r requirements-dev.txt
pyinstaller packaging\xlsform_studio_cli.spec     :: -> dist\xlsform-studio.exe
```

The CLI packages into a single standalone `.exe` (no Python needed on the
target). The Streamlit UI ships as a small virtual-environment launcher.

---

## Deployment

The tool has no database and no cross-session server state — every browser
session that hits the Streamlit UI gets its own private temp directory
(`tempfile.mkdtemp()`, swept automatically after 24h), so one visitor's
survey content is never written where another visitor's session could see
it. That makes "host it online for a team" a matter of running the existing
app on a public URL, not a rearchitecture.

**Docker / CI (headless, CLI only).** A minimal container needs Python
3.11+, the package, and nothing else for the deterministic pipeline:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .
ENTRYPOINT ["xlsform-studio"]
```

```bash
docker build -t xlsform-studio .
docker run --rm -v "$PWD:/data" xlsform-studio /data/survey.docx -o /data/out
```

In a CI pipeline, run `xlsform-studio survey.docx -o build/` as a build
step and check its exit code: `0` means the form validated, `1` means
validation found errors (see [Usage](#usage)). No network egress is
required unless you explicitly pass `--ai` — the pipeline is airtight for
regulated or offline environments by default.

**Server (Streamlit UI).** The repo root [`Dockerfile`](Dockerfile) builds
and serves the graphical app:

```bash
docker build -t xlsform-studio-web .
docker run --rm -p 8501:8501 xlsform-studio-web
# with AI enabled for every visitor, using your own key/budget:
docker run --rm -p 8501:8501 -e DEEPSEEK_API_KEY=sk-... xlsform-studio-web
```

It respects `$PORT` (so it drops into any container platform's expected
contract) and includes a Streamlit health-check endpoint
(`/_stcore/health`). Locally, `python run_ui.py` does the same without
Docker. The app is stateless per session, so no special session affinity
is needed beyond what Streamlit itself requires — you can run more than
one replica behind a load balancer.

**Where to host it.** Any platform that runs an arbitrary Docker container
on a public URL works; roughly in order of setup effort:

| Platform | Why you'd pick it |
| --- | --- |
| **Render** / **Railway** | Point at this repo, it detects the `Dockerfile`, builds, and gives you a URL with HTTPS - least setup for a small team. Free/cheap tiers exist but sleep on inactivity; a paid tier keeps it always-on. |
| **Fly.io** | Similar simplicity with more control over region/scaling; needs their CLI once to `fly launch`. |
| **A plain VPS** (DigitalOcean, a Hetzner box, EC2) | Full control, predictable flat cost, but you own patching/updates/TLS (`docker run` behind Caddy or nginx for free auto-HTTPS is the least-effort combo). |
| **Streamlit Community Cloud** | Purpose-built for Streamlit apps and genuinely the least effort of all, but requires a public GitHub repo (or their paid tier for private) and gives you the least infrastructure control. |

Whichever you pick, set `DEEPSEEK_API_KEY` as a platform secret (never
commit it) if you want AI features on for every visitor rather than
requiring each person to supply their own key.

**Configuration knobs** (all optional; the tool runs with sane defaults if
none are set):

| Variable | Purpose |
| --- | --- |
| `DEEPSEEK_API_KEY` | Enables the optional AI layer. Unset = fully deterministic, zero network calls. |
| `XLSFS_OUTPUT_DIR` | Override the default output directory. |
| `XLSFS_DEEPSEEK_BASE_URL` / `XLSFS_DEEPSEEK_MODEL` | Point the AI layer at a different DeepSeek-compatible endpoint/model. |
| `XLSFORM_STUDIO_LOG_LEVEL` | Diagnostic log verbosity for the Streamlit UI (`DEBUG`/`INFO`/`WARNING`/`ERROR`); the CLI uses `--log-level` instead. |

**Error recovery.** Every step degrades independently rather than taking
the whole run down:
- A parser failure on one file doesn't affect other files in a batch —
  each `xlsform-studio` invocation is one process, one exit code.
- Any AI feature failure (network error, malformed response, missing key)
  falls back to the deterministic result for that feature and logs a
  `[AI] ...` note in the assumption log; it never aborts the run.
- Validation errors are reported, not thrown — the XLSForm and full
  documentation package are still written even when the form is invalid,
  so you always have something to inspect and fix.

---

## Troubleshooting

**"AI enrichment was skipped and the deterministic result stands."**
Either `DEEPSEEK_API_KEY` isn't set, or the form exceeds the AI
question-count ceiling (2,000 questions, to keep prompts inside the
model's context window and bound per-run API cost). The deterministic
output is complete and unaffected either way — AI is enrichment, not a
dependency.

**The AI API is down / rate-limited / times out.**
Nothing to do — the run still completes. Each AI feature independently
falls back to the deterministic result and logs why in the assumption
log. Re-run later, or without `--ai`, to get the same form without the
AI notes.

**A form with 500+ questions feels slow.**
The deterministic pipeline scales roughly linearly with question and
choice-list count and has been used well past this size, but very large
choice lists (thousands of options) will slow the consistency validator's
pairwise near-duplicate check the most; if that becomes a bottleneck,
disable AI features (they add the most latency per question) and profile
which validator is dominant before assuming it's the AI layer.

**"How do I trust an AI suggestion?"**
You don't have to — every AI mutation is validated deterministically at
apply time (see [AI authoring & enrichment](#ai-authoring--enrichment)),
advisory suggestions are never applied without explicit accept, and every
applied change is tagged "AI-suggested" in the assumption log with the
original value preserved. Run `xlsform-studio ... --log-level DEBUG` to
see exactly which features ran and what each one returned.

**I need to see what a run actually did, not just the output.**
Pass `--log-level DEBUG` (CLI) or set `XLSFORM_STUDIO_LOG_LEVEL=DEBUG`
before `streamlit run` (UI). This traces every AI feature's run/skip
decision, every network call's timing and outcome, and every AI
suggestion's accept/apply/reject outcome — without ever printing prompt
content or the API key.

**Where did my file go?**
Every run writes into a timestamped subfolder of the output directory
(`<form_id>_<YYYYMMDD_HHMMSS>/`), so re-running never overwrites a
previous package. `version_history.json` at the output root is the
append-only index across runs.

---

## License

MIT.
