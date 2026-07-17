[← Documentation index](../README.md#documentation)

# Usage & API

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

# optional AI enrichment (requires DEEPSEEK_API_KEY) — see docs/ai.md
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
