---
name: questionnaire-to-xlsform
description: >-
  Convert a questionnaire or survey into a deployment-ready, validated XLSForm
  package for Kobo, KoboToolbox, ODK, SurveyCTO, Ona or CommCare. Use this
  whenever someone hands you a survey, questionnaire, data-collection form, or
  interview instrument — in Word, PDF, Excel, CSV, an image/photo, or just
  pasted text — and wants it turned into an XLSForm, an .xlsx survey, a Kobo
  form, an ODK form, or "a form I can upload to KoboToolbox/SurveyCTO". Also
  use it for "build me a survey form", "digitise this paper questionnaire",
  "make this into a mobile data collection form", or when they mention survey
  logic like skip patterns, relevance, constraints, choice lists, repeat
  groups/rosters, or select_one/select_multiple. Trigger even when they don't
  say the word "XLSForm" — a survey headed for mobile/tablet data collection
  almost always means XLSForm.
---

# Questionnaire → XLSForm

Turn a source questionnaire into a complete, **validated** XLSForm package.

The hard part of this job is not typing a spreadsheet — it is getting the
machine-readable details right: safe unique variable names, correct XLSForm
types, valid XPath in `relevant`/`constraint`/`calculation`, choice lists that
are shared rather than duplicated, and a form that actually converts to a valid
ODK XForm. Hand-typed XLSForms fail on exactly these points.

So this skill splits the work the way it should be split:

- **You (the model) do the interpretation.** You read the questionnaire and
  express it as a clean, structured JSON form definition — deciding what each
  question means, which options belong to it, and where skip logic applies.
  This is the judgement a person (or a large model) is good at.
- **XLSForm Studio's deterministic engine does the compilation.** A helper
  script feeds your JSON through the engine, which assigns types, generates
  safe variable names, turns natural-language logic into real XPath, builds and
  de-duplicates choice lists, exports the workbook in the target platform's
  dialect, and validates the result with pyxform. Rules — not guesses — produce
  every fragile detail.

Because you play the authoring role, **no API key is required**: the engine runs
in its deterministic mode.

## Prerequisite: the engine

This skill wraps the **XLSForm Studio** engine (the `xlsform_studio` Python
package). Confirm it is importable before you start:

```bash
python -c "import xlsform_studio" 2>/dev/null && echo OK || echo MISSING
```

If it prints `MISSING`, install it from the XLSForm Studio repository root
(the repo this skill ships with):

```bash
pip install -r requirements.txt   # or: pip install -e .
```

The bundled script auto-discovers a `xlsform_studio` checkout in a parent
directory, so if you are working inside the repo the import usually just works
once the dependencies are installed.

## Workflow

### 1. Read the source questionnaire

Get the questions in front of you, whatever the format:

- **Text / Markdown / pasted content** — read it directly.
- **Word (.docx), PDF, Excel (.xlsx/.csv)** — use the `Read` tool, which
  extracts their text; for spreadsheets, inspect the columns.
- **Image / photo / scan of a paper form** — read the image and transcribe the
  questions and options faithfully.

Do not skip options, section headings, or instructions like "if yes, ask…" —
those become choice lists and skip logic.

### 2. Author the JSON form definition

Translate what you read into the engine's JSON schema. The minimum is one
`question` per item; everything else the engine can infer, but the more you
specify, the more faithful the form. Read
[`references/json-schema.md`](references/json-schema.md) for the full field
list, and [`references/authoring-guide.md`](references/authoring-guide.md) for
how to make good authoring decisions (type inference, writing skip logic the
engine understands, repeat groups/rosters, "other (specify)", coded options,
translations).

A compact example:

```json
{
  "settings": {"form_title": "Household Survey", "form_id": "household_survey", "version": "1"},
  "survey": [
    {"question": "Head of household name", "section": "Household", "required": true},
    {"question": "Do you own this dwelling?", "choices": ["Yes", "No"], "required": true, "section": "Housing"},
    {"question": "How many years have you lived here?", "type": "integer", "logic": "ask if yes", "section": "Housing"},
    {"question": "Which utilities do you have?", "type": "select_multiple",
     "choices": ["Electricity", "Piped water", "Internet"], "section": "Housing"}
  ]
}
```

Write the JSON to a file, e.g. `form.json`.

### 3. Compile, validate, and export

Run the bundled script. Point `--target` at the platform the user named (or
omit it for a generic XLSForm):

```bash
python scripts/generate.py form.json --target kobo --output ./xlsform_output
```

Valid targets: `kobo`, `surveycto`, `odk`, `ona`, `commcare`.

The script prints whether validation **PASSED** or **FAILED**, lists any errors
and warnings, and writes the full package to the output folder: the XLSForm
`.xlsx`, a data dictionary, a QA report, a logic map, and an
`assumptions_to_verify.md` recording every heuristic decision the engine made.

### 4. Fix errors and review assumptions

- **If validation FAILED** (non-zero exit), read the reported errors, correct
  the JSON — usually a broken `relevant`/`constraint` reference or a malformed
  choice — and re-run. Do not hand the user a form that fails validation.
- **If it PASSED**, skim `assumptions_to_verify.md`. Where the engine guessed a
  type, a constraint range, or how to invert a skip pattern, sanity-check it
  against the source. If a guess is wrong, set the field explicitly in the JSON
  and re-run. Warnings are advisory — mention the load-bearing ones to the user
  rather than silently accepting them.

### 5. Report back

Tell the user the form validated, where the `.xlsx` is, which platform dialect
it is in, and anything they should verify before deploying (e.g. a skip-to
pattern the engine surfaced for review, or an inferred constraint range).

## Principle: transparent, not silently automatic

The engine records every inference so it can be checked, and surfaces the
things it cannot safely resolve (like un-invertible "skip to Q20" jumps) as
review notes rather than quietly guessing. Carry that spirit into how you
report: be clear about what was inferred versus what the source stated, so the
person can trust and correct the form before it goes to the field.
