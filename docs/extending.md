[← Documentation index](../README.md#documentation)

# Extending the rules

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

## Other editable YAML

Everything a non-programmer might want to tune lives in
`xlsform_studio/knowledge/`, not in code:

* **`platforms.yaml`** — the deployment-target profiles (column dialects,
  supported types, naming standards, per-platform tips). Adding a platform is
  a YAML edit; the UI, CLI and compatibility matrix pick it up automatically.
  See [Validation & quality](validation.md#platform-specific-standards).
* **`design_intelligence.yaml`** — the survey-methodology vocabularies behind
  the [Survey Design Score](validation.md#survey-design-score-methodology-intelligence):
  sensitive topics, recall-window patterns, ordinal scale families, leading
  phrases. Tune what counts as a methodological issue without touching Python.

---
