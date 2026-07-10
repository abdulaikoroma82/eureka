# XLSForm Architect

**A standalone, rule-based compiler that turns questionnaires into
deployment-ready XLSForms for KoboToolbox, SurveyCTO, ODK, Ona and CommCare.**

XLSForm Architect lets a survey designer, M&E officer or researcher drop in a
questionnaire of **any kind** (Word, Excel, PDF, CSV or JSON) and get back a
complete, validated XLSForm package — the spreadsheet plus a data dictionary,
QA report, assumption log, logic map and version history. It applies the
**standard rules of the XLSForm specification**; it is not tied to any
particular survey domain.

> **No AI service required.** The tool contains no dependency on Claude,
> ChatGPT, the OpenAI API or any subscription service. All of its intelligence
> comes from deterministic **parsers, rule engines, templates and validators**.
> It runs entirely offline on a laptop or an internal server.

> 🟢 **New to this / non-technical?** Start with the plain-language
> [Getting Started guide](docs/GETTING_STARTED.md) — no coding needed.

---

## Why it exists

Hand-coding XLSForms is slow and error-prone: mistyped variable names, broken
`relevant` references, missing choice lists, inconsistent constraints. XLSForm
Architect standardises that work and catches the errors before deployment.

---

## Architecture

```
              User Interface  (Streamlit UI  /  CLI)
                      |
              Application Controller  (app/workflow.py)
                      |
      ---------------------------------------------
      |                  |                        |
   Parser            Rule Engine              Validator
 (parsers/)          (engine/)              (validation/)
      |                  |                        |
      ---------------------------------------------
                      |
              XLSForm Generator  (xlsform/)
                      |
                Output Package
   (XLSForm · data dictionary · QA report · assumption
    log · logic map · version history)
```

All stages communicate through one intermediate representation
(`xlsform_architect/models.py`): a `Questionnaire` of `Question`, `Choice` and
`ChoiceList` objects. A parser only has to produce a `Questionnaire`; everything
downstream then works unchanged.

### Project layout

```
xlsform_architect/
├── app/            # controller, config, CLI (main.py) and Streamlit UI (ui.py)
├── parsers/        # DOCX / XLSX / PDF / CSV / JSON / text parsers  (Module 1)
├── engine/         # classifier, naming, logic, constraint, calculation  (Modules 2,3,5,6,7)
├── xlsform/        # survey / choices / settings builders + exporter  (Module 4)
├── validation/     # structure / logic / deployment validators + report  (Module 9)
├── knowledge/      # editable YAML rule packs  (Module 8)
├── templates/      # blank XLSForm template
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

Or install as a package (gives you the `xlsform-architect` command):

```bash
pip install -e .
```

---

## Usage

### 1. Graphical app (Streamlit)

```bash
python run_ui.py
# or:  streamlit run xlsform_architect/app/ui.py
```

Then in the browser: upload a questionnaire → pick a target (Kobo, SurveyCTO,
ODK, Ona, CommCare) → click **Generate XLSForm**. Live processing steps are
shown, followed by the validation result and download buttons for the XLSForm
and the full `.zip` package.

### 2. Command line

```bash
python -m xlsform_architect.app.main xlsform_architect/examples/event_registration.json
python -m xlsform_architect.app.main survey.docx --title "Household Survey" --output ./out
# target a platform: validates against ITS standards and writes ITS dialect
python -m xlsform_architect.app.main survey.docx --target surveycto
# use a customised ruleset instead of the bundled standard rules
python -m xlsform_architect.app.main survey.docx --rules ./my_rules
# after `pip install -e .`
xlsform-architect design.csv --target kobo
```

The process exits non-zero if validation finds blocking errors, so it slots
into CI / batch pipelines.

### 3. As a library

```python
from xlsform_architect.app.workflow import Workflow

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

Only `question` is mandatory. The engine fills in the type, variable name,
choice list, relevance, constraint and any derived calculations.

---

## What the rule engine does (deterministically)

| Module | Behaviour | Example |
| --- | --- | --- |
| **Classifier** (M2) | Assigns XLSForm types | `Yes/No → select_one yes_no`, `age → integer`, `amount → decimal`, `GPS → geopoint`, `photo → image` |
| **Variable namer** (M3) | Safe, unique names | `"Preferred contact method" → preferred_contact_method` |
| **Logic engine** (M5) | Natural language → expressions | `"if yes" → ${prev}='1'`, `"under 5 years" → ${age_months}<60` |
| **Constraint engine** (M6) | Validation ranges | `age → . >= 0 and . <= 120`, `% → . >= 0 and . <= 100`, `date → . <= today()` |
| **Calculation engine** (M7) | Derived fields | age in years from a date of birth |

Every decision is recorded in the **assumption log** so it can be reviewed.

---

## The rule pack (editable, no code changes)

Platform profiles live in `xlsform_architect/knowledge/platforms.yaml`
(dialects, supported types, naming standards, per-platform tips). All other
standard rules live in `xlsform_architect/knowledge/xlsform_rules.yaml`:

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

---

## Platform-specific standards

Choosing a target platform genuinely changes the output — the tool applies
**that platform's** rules, not just the generic XLSForm spec. The profiles
live in `xlsform_architect/knowledge/platforms.yaml` (editable, no code
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

XLSForm Architect covers the **XLSForm family** of mobile data collection
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
  choice lists.
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
> checks full XForm runtime semantics). Every platform still runs its own
> validation when you upload — treat that as the final authoritative check.

Results are written to `QA_Report.pdf` in the output package.

---

## Output package

Each run writes a timestamped folder under `output/` containing:

1. `*.xlsx` — the XLSForm (survey / choices / settings sheets)
2. `*_data_dictionary.xlsx` — every variable, type, choices, constraint, calculation
3. `QA_Report.pdf` — the validation report
4. `assumption_log.md` — every deterministic decision made
5. `logic_map.md` — relevance / constraint / calculation relationships
6. `version_history.json` — append-only audit trail across runs

---

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

The suite (`xlsform_architect/tests/`) covers the naming, classification,
logic, constraint and calculation engines, the builders/exporter, the
validators, every parser and the end-to-end workflow.

---

## Packaging as a Windows application

See [`packaging/README.md`](packaging/README.md). In short:

```bat
pip install -r requirements-dev.txt
pyinstaller packaging\xlsform_architect_cli.spec     :: -> dist\xlsform-architect.exe
```

The CLI packages into a single standalone `.exe` (no Python needed on the
target). The Streamlit UI ships as a small virtual-environment launcher.

---

## Development iterations

The system was built in the planned iterations: (1) JSON → XLSForm, (2) validation
engine, (3) Excel/CSV parser, (4) Word/PDF parser, (5) rule engine, (6)
standard XLSForm knowledge pack, (7) Streamlit interface, (8) Windows packaging.

## License

MIT.
