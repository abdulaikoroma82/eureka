# Authoring guide

How to turn a messy source questionnaire into good JSON. The engine is strong
at mechanics (naming, XPath, choice de-duplication, validation); your job is to
capture *intent* faithfully and lean on the engine for the rest.

## Let the engine infer, override when you know better

You do **not** have to specify a type, name, or constraint for every question.
The classifier reads the label and picks a sensible XLSForm type; the variable
namer produces safe unique names; the constraint engine adds range checks. Only
set a field explicitly when the source implies something the label alone would
not reveal, or when an inference in `assumptions_to_verify.md` came out wrong.

### Type inference cues (what the classifier keys on)

| Label looks like | Inferred type |
| --- | --- |
| A yes/no or two-option question | `select_one` (a shared yes/no list) |
| A list of options under the question | `select_one` (or `select_multiple` if "select all that apply") |
| "age", "how many", "number of" | `integer` |
| "amount", "cost", "percentage", a decimal quantity | `decimal` |
| "date of…", "when" | `date` |
| "GPS", "location", "coordinates" | `geopoint` |
| "photo", "take a picture" | `image` |
| A statement/heading with no answer | `note` |
| A value derived from other answers | `calculate` |

When in doubt for a select, set `type` and `choices` explicitly so the options
are not lost.

### Single vs multiple select

If the source says "select all that apply", "tick all", or the options are not
mutually exclusive, use `select_multiple`. Otherwise `select_one`.

## Writing skip logic the engine understands

Prefer the natural-language `logic` field — the logic engine parses a wide
range of phrasings into correct XPath, and it resolves references against the
other questions for you:

| You write in `logic` | Becomes (roughly) |
| --- | --- |
| `"ask if yes"` / `"if yes"` | show when the preceding yes/no answer is yes |
| `"if question 4 is married"` | resolves Q4's variable and coded option → `${q4}='2'` |
| `"if age over 18"` | `${age} > 18` |
| `"between 18 and 65"` (as a constraint) | `. >= 18 and . <= 65` |
| `"unless married"` | negation → `not(${marital}='married')` |
| a multi-select condition | uses `selected(${var}, 'code')` |

Guidelines:

- Reference earlier questions by their number (`"if question 4 is yes"`) or by
  an unambiguous keyword. Ambiguous references may not resolve — check the
  assumption log.
- `"skip to question 20"` style jumps cannot be safely inverted into relevance,
  so the engine surfaces them as a review note instead of guessing. If you see
  one, rewrite it as positive relevance on the questions that *should* show
  (e.g. mark the in-between questions `"ask if <condition>"`).
- If you already have an exact expression, use `relevant` (raw XPath) instead
  of `logic`.

## Constraints

Let the constraint engine infer ranges from the type (age `0–120`, percentage
`0–100`, dates `<= today()`) unless the source states specific bounds — then set
`constraint` explicitly, e.g. `". >= 15 and . <= 49"` for women of reproductive
age, and add a `constraint_message`.

## "Other (specify)"

When a select offers an "Other" option that needs a written follow-up, just
include `"Other"` in `choices`. The engine automatically adds a text question
shown only when Other is selected — you do not build it yourself.

## Coded options

When the source assigns codes to options ("1 = Yes, 2 = No, 96 = Other,
99 = Don't know"), pass them as `"code=Label"` strings so the stored value
matches the codebook:

```json
{"question": "Marital status", "type": "select_one",
 "choices": ["1=Never married", "2=Married", "3=Widowed", "96=Other"]}
```

Special missing-data codes (96/98/99 etc.) are preserved; the QA report will
flag outliers so you can confirm the analysis plan treats them as missing.

## Repeat groups (rosters)

A "for each …" block — per household member, per child, per visit — is a repeat.
Give every question in it the same `section` and `section_type: "repeat"`.
Remember the **scope rule**: logic in a non-repeat question cannot reference a
variable defined inside a repeat (the validator will error on it). Keep
member-level logic inside the member repeat.

## Matrix / grid questions

A grid (items down the side, a rating scale across the top) becomes one
`select_one` per row, all sharing one choice list. Author it as several
questions that reuse the same options — the engine merges identical option sets
into a single shared list automatically, so do not worry about duplication.

## Translations and media

Add translation columns as `label::<Language> (code)` keys on the question
(and `hint::…` similarly). Media columns like `media::image` are passed through
too. These are carried straight into the exported workbook.

## Sections and order

Group related questions with `section`. Keep the survey order the respondent
experiences — the engine preserves order and only reorganises choice lists.

## After compiling: reading the outputs

- `assumptions_to_verify.md` — every heuristic decision (inferred types, choice
  lists, relevance, constraints). Skim it; correct the JSON where a guess is
  wrong and re-run.
- Validation **errors** block deployment — fix them. Common ones: a
  `relevant`/`constraint` referencing a name that does not exist (typo, or a
  repeat-scope violation) and malformed choice lists.
- Validation **warnings** are advisory (e.g. a calculation that may reference a
  blank field, an outlier code). Judge each; mention the load-bearing ones to
  the user.
