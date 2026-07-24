# JSON form-definition schema

The input the compile script consumes. It is the same schema XLSForm Studio
accepts as a `.json` questionnaire, so anything here is exact — no guessing.

## Top-level shape

```json
{
  "settings": { ... },
  "survey":   [ { ...question... }, ... ],
  "choices":  { ...optional explicit choice lists... }
}
```

Only `survey` is required. `settings` and `choices` are optional.

## `settings`

| Key | Meaning |
| --- | --- |
| `form_title` | Human-readable title (shown to enumerators). Default `"Untitled Form"`. |
| `form_id` | Machine id. Lowercase, no spaces. Derived from the title if omitted. |
| `version` | Version string, e.g. `"1"` or a date stamp like `"2026072401"`. |
| `default_language` | Optional default language label. |
| `style` | Optional form `style` (e.g. `"pages"`, `"theme-grid"`). |

## `survey` — one object per question

Only `question` is mandatory; the engine infers the rest. Supply more to
override the inference.

| Key | Type | Meaning |
| --- | --- | --- |
| `question` | string | **Required.** The question text / label as a respondent sees it. (Aliases: `label`, `raw_label`.) |
| `type` | string | XLSForm type. Omit to let the classifier infer it. Examples: `text`, `integer`, `decimal`, `select_one`, `select_multiple`, `date`, `time`, `datetime`, `geopoint`, `image`, `audio`, `barcode`, `note`, `calculate`. For selects you may write just `select_one` and give `choices`; the list name is generated. |
| `choices` | array | Options for a select. Strings (`["Yes","No"]`), `"code=Label"` strings (`["1=Yes","2=No"]`) to fix the stored code, or `{"name","label"}` objects. |
| `required` | bool | Whether an answer is mandatory. |
| `logic` | string | **Natural-language** skip/relevance, e.g. `"ask if yes"`, `"if question 4 is married"`. The engine turns it into a `relevant` XPath. See the authoring guide. |
| `relevant` | string | A raw XPath relevance expression, if you already have one (e.g. `"${owns}='yes'"`). Use `logic` unless you need exact control. |
| `constraint` | string | XPath constraint on the answer, e.g. `". >= 0 and . <= 120"`. Omit to let the constraint engine infer a range from the type. |
| `constraint_message` | string | Message shown when the constraint fails. |
| `calculation` | string | XPath for a `calculate` field, e.g. an age derived from a date. |
| `hint` | string | Helper text under the question. |
| `name` | string | Force the variable name. Otherwise a safe unique name is generated from the label. |
| `section` | string | Group/section the question belongs to; consecutive same-section questions become one `begin group … end group` block. |
| `section_type` | string | `"group"` (default) or `"repeat"`. See repeats below. |
| `repeat` | bool | Shorthand: `true` marks this question's section as a repeat group. |
| `instruction` | string | Enumerator instruction / interviewer note. |
| `default` | string | Default answer value. |
| `appearance` | string | XLSForm `appearance` (e.g. `"minimal"`, `"likert"`, `"multiline"`). |
| `choice_filter` | string | Cascading-select filter expression. |
| `list_name` | string | Explicit choice-list name to reference or define. |
| `label::<Lang> (code)` | string | Translation passthrough column, e.g. `"label::French (fr)"`. Any key containing `::` is carried through to the workbook (also works for `hint::…`, `media::image`, etc.). |

## Repeat groups (rosters)

A block of questions asked once **per entity** (each household member, each
child, each visit). Mark every question in the block with the same `section`
and `section_type: "repeat"` (or `"repeat": true`):

```json
{"question": "Member name",  "section": "Members", "section_type": "repeat", "required": true},
{"question": "Age in years", "section": "Members", "section_type": "repeat", "type": "integer"}
```

**Scope rule:** a variable defined *inside* a repeat is not visible *outside*
it. A `relevant`/`constraint`/`calculation` in a non-repeat question that
references a repeat variable is a validation error — keep such logic inside the
same repeat, or use `indexed-repeat()`. The validator will catch violations.

## Explicit `choices` lists (optional)

Usually you just put `choices` on the question and let the engine name and
share the list. Supply a top-level `choices` map only when you want to define a
reusable or cascading list explicitly, or attach per-option extra columns:

```json
"choices": {
  "yes_no": [
    {"name": "yes", "label": "Yes"},
    {"name": "no",  "label": "No"}
  ],
  "district": [
    {"name": "d1", "label": "Northern", "region": "north"}
  ]
}
```

Extra keys on a choice object (like `region` above) become passthrough columns
on the choices sheet — the mechanism behind cascading selects.
