[← Documentation index](../README.md#documentation)

# Validation & quality

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

---

## Validation & deployment compatibility

The validator runs in layers:

* **Structure** — survey/choices/settings present, every question typed and
  named, `begin/end group` & `begin/end repeat` markers balanced, and the
  `form_id` a safe identifier (spaces or punctuation that platforms reject on
  upload are flagged).
* **Logic** — no duplicate names, no broken `${…}` references, no missing/empty
  choice lists, no **group/repeat name colliding** with a question (they share
  one `${…}` namespace), no **whitespace in choice codes** (a space in a
  `select_multiple` code silently splits the stored value), and **no dead
  comparisons**: `${sex}='femalee'` (a typo) or a value the referenced list can
  never hold is flagged, because it would deploy fine and simply never fire.
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

---

## Survey Design Score (methodology intelligence)

Validation checks that a form is *well-formed*. The **Survey Design Score**
checks something no XLSForm tool usually does: whether it is *well-designed
as a measurement instrument* — the judgement a principal investigator, M&E
specialist or survey methodologist brings. It answers "will this produce
valid data?", not "will it compile?". This is XLSForm Studio's move from form
*generation* into survey **methodology assistance**.

It scores the form 0–100 across ten methodological dimensions:

| Dimension | What it checks |
| --- | --- |
| **Question order** | Sensitive topics placed after rapport, screening/consent first, no forward dependencies |
| **Module flow** | Coherent, balanced sections rather than one giant block or scattered singletons |
| **Cognitive burden** | Open-ended load, over-long option lists, wordy stems, densely nested logic |
| **Recall period consistency** | Recall windows present, bounded (beyond ~12 months invites recall bias), and standardised across questions |
| **Scale consistency** | Answer scales of one family share point count and direction (no mixed 4-/5-point Likert for one construct) |
| **Enumerator burden** | Skip/constraint density and roster load the interviewer must manage |
| **Respondent burden** | Length and effort asked of the respondent (reuses the duration estimate) |
| **Objective coverage** | Each stated study objective is measured (assessed only when objectives are supplied) |
| **Redundancy detection** | Near-duplicate questions asking the same thing |
| **Measurement validity** | Double-barreled, leading/loaded, or escape-less (no "don't know") items; forced-choice scales with no neutral midpoint |

**It is deterministic and offline-first**, exactly like the Form Quality
Index: every dimension is computed arithmetically from the form, so the same
form always scores the same, and no API key is required. Where a dimension
benefits from the AI reviewers, their *existing* findings are folded in — so
enabling AI enriches the score but is never needed for it. The headline
**rating** (`publication-ready` · `sound` · `needs methodological review` ·
`high measurement risk`) is gated by the *weakest* dimension, so one serious
flaw can't be diluted away by everything else being clean. A dimension the
tool genuinely can't assess (objective coverage with no objectives supplied)
is marked **not assessed** and excluded from the average rather than guessed.

The methodology vocabularies it reads — sensitive topics, recall-window
patterns, ordinal scale families, leading phrases — live in editable YAML
(`xlsform_studio/knowledge/design_intelligence.yaml`), so a methodologist can
tune what counts without touching Python. The score appears in the QA report,
the app's **📊 Quality** tab, the CLI summary, and its own
`survey_design_report.md` in every output package.

---

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
