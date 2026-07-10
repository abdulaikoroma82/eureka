# XLSForm Architect

**A standalone, rule-based compiler that turns questionnaires into
deployment-ready XLSForms for KoboToolbox, SurveyCTO and ODK.**

XLSForm Architect lets an M&E officer, survey designer or nutrition programme
specialist drop in a questionnaire (Word, Excel, PDF, CSV or JSON) and get back
a complete, validated XLSForm package — the spreadsheet plus a data dictionary,
QA report, assumption log, logic map and version history.

> **No AI service required.** The tool contains no dependency on Claude,
> ChatGPT, the OpenAI API or any subscription service. All of its intelligence
> comes from deterministic **parsers, rule engines, templates and validators**.
> It runs entirely offline on a laptop or an internal server.

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

Then in the browser: upload a questionnaire → pick a survey category (IMAM,
VAS+D, MMS, ANC, Household, Custom) → pick a target (Kobo, SurveyCTO, ODK) →
click **Generate XLSForm**. Live processing steps are shown, followed by the
validation result and download buttons for the XLSForm and the full `.zip`
package.

### 2. Command line

```bash
python -m xlsform_architect.app.main xlsform_architect/examples/imam_otp.json --category imam
python -m xlsform_architect.app.main survey.docx --title "OTP Register" --output ./out
# after `pip install -e .`
xlsform-architect design.csv --category household
```

The process exits non-zero if validation finds blocking errors, so it slots
into CI / batch pipelines.

### 3. As a library

```python
from xlsform_architect.app.workflow import Workflow

result = Workflow().run_from_dict({
    "settings": {"form_title": "OTP Register"},
    "category": "imam",
    "survey": [
        {"question": "Is the child currently enrolled in OTP?",
         "choices": ["Yes", "No"], "required": True},
        {"question": "Admission date", "logic": "ask if yes"},
        {"question": "MUAC (cm)"},
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
  "category": "imam",
  "survey": [
    {
      "question": "Is the child currently enrolled in OTP?",
      "type": "select_one",              // optional — inferred if omitted
      "choices": ["Yes", "No"],          // optional
      "required": true,                  // optional
      "logic": "ask admission date if yes",  // natural language → relevant
      "section": "Identification"        // optional grouping
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
| **Classifier** (M2) | Assigns XLSForm types | `Yes/No → select_one yes_no`, `age → integer`, `weight → decimal`, `GPS → geopoint`, `photo → image` |
| **Variable namer** (M3) | Safe, unique names | `"Child age in months" → child_age_months` |
| **Logic engine** (M5) | Natural language → expressions | `"if yes" → ${prev}='1'`, `"under 5 years" → ${age_months}<60` |
| **Constraint engine** (M6) | Validation ranges | `age(months) → . >= 0 and . <= 60`, `% → . >= 0 and . <= 100`, `date → . <= today()` |
| **Calculation engine** (M7) | Derived fields | age from DOB, BMI, MUAC class (SAM/MAM/Normal), IMAM admission category |

Every decision is recorded in the **assumption log** so it can be reviewed.

---

## Knowledge packs (editable, no code changes)

All thresholds and rules live in `xlsform_architect/knowledge/*.yaml`:

* `xlsform_rules.yaml` — type keywords, constraints, naming, logic vocabulary
* `nutrition_rules.yaml` — MUAC / BMI / anthropometry thresholds, reusable lists
* `imam_rules.yaml` — OTP/SC/TSFP admission & discharge criteria
* `mms_rules.yaml` — MMS and VAS+D indicators and doses
* `dhis2_dictionary.yaml` — variable → DHIS2 data-element mappings

Edit the YAML to adapt the tool to a national protocol — the Python code does
not change.

---

## Validation & deployment compatibility

Before export the validator checks:

* **Structure** — survey/choices/settings present, every question typed and named
* **Logic** — no duplicate names, no broken `${…}` references, no missing/empty
  choice lists
* **Deployment** — valid ODK/XML identifiers, no reserved words, recognised
  types — reported per platform (Kobo / SurveyCTO / ODK)

Results are written to `QA_Report.pdf` in the output package.

---

## Output package

Each run writes a timestamped folder under `output/` containing:

1. `*.xlsx` — the XLSForm (survey / choices / settings sheets)
2. `*_data_dictionary.xlsx` — every variable, type, choices, constraint, DHIS2 map
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
nutrition / M&E knowledge packs, (7) Streamlit interface, (8) Windows packaging.

## License

MIT.
