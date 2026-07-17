[← Documentation index](../README.md#documentation)

# AI authoring & enrichment

XLSForm Studio uses the model ([DeepSeek](https://api-docs.deepseek.com/)) in
**two distinct roles**. Keep them separate — they have opposite requirements.

## 1. AI-assisted authoring — *required*

The model **drafts every field of the form**: types, machine names, labels,
hints, relevance/skip logic, constraints, calculations and choice lists.
Deterministic rules bracket it (the parser lays out the scaffold; the
standards enforcer and validators check the draft), but the drafting itself is
the model's job. There is **no offline authoring fallback** in the shipped
product, so:

- a run **requires** a valid `DEEPSEEK_API_KEY` and network egress to the API;
- a missing key stops the run with *"a DeepSeek API key is required"*; a
  rejected key reports *"DeepSeek rejected the API key"*;
- the `XLSFS_AUTHORING=deterministic` rule-engine compiler exists only as an
  internal test seam and is never selected by the UI or CLI.

You then **review and edit** the AI draft before download — see
[Reviewing the AI draft](architecture.md).

## 2. AI enrichment — *optional*

On top of authoring, a set of **enrichment passes** refine the draft:
translation, a holistic quality review, plain-English explanations of the
validator's findings, and advisory grouping/rewording/ordering/instruction
suggestions. These are **off by default**, are enabled per-feature, and
**fail open** — a network error, malformed response or rate-limit skips just
that pass and leaves the authored form intact. They only ever *annotate or
refine* the authored form; they never re-author it.

The rest of this page details the enrichment features, how AI and rules
co-share certain outputs, what is deliberately kept out of the model's hands,
setup, and the safety/cost design.

---

## Enrichment features (all optional)

| Feature | What it does | Why it can't be deterministic |
| --- | --- | --- |
| **Translation** | Generates `label::French (fr)`-style columns from your English labels — **only for labels you haven't already translated yourself**; finished translations are cached locally (`.translation_cache.json`) so regenerating a form doesn't re-pay for unchanged text | Translation is language generation, not pattern matching |
| **Cross-field constraints** | Suggests constraints that depend on another question, e.g. "end date must be on/after start date" — **combined with `and`** if the field already has an authored constraint | A per-question check only ever looks at one question at a time — it structurally cannot see the relationship between two |
| **AI quality review** | A holistic second pass flagging things structural checks can't see — semantic contradictions, unclear names, and respondent-experience traps (ambiguous phrasing, contradictory option lists, redundant questions, incoherent skip chains); advisory only | Requires reasoning across multiple fields' relationship to each other |
| **Explain findings** | Adds a one-sentence plain-English explanation to the validator's own findings, after validation runs | Rules own every fact (level, category, message); AI only makes them easier to read |
| **Missing-question detection** | Infers the survey's purpose and flags questions it probably needs but lacks (weight + MUAC with no height blocks weight-for-height) — advisory findings only, the tool **never adds questions** | Recognising that a set of questions implies an absent member is domain reasoning, not pattern matching |
| **Objective coverage matrix** | You list your study objectives; it maps each to the questions that inform it and flags gaps (`coverage_matrix.md` + Quality tab). Every cited question name is verified to exist — invalid references are discarded | Judging that two questions together measure "access to safe water" is semantics; the question inventory and reference checks stay 100% rules |
| **Indicator matrix** | Drafts an M&E reporting framework from the compiled questions: indicator, source questions (verified to exist), aggregation level, means of verification (`indicator_matrix.md`) | Which questions feed which indicator is meaning, not matching |
| **Question grouping** *(suggestion-only)* | Proposes logical sections for a form whose source document didn't provide them | "Water source" and "latrine type" belonging together is a semantic judgement |
| **Question rewording** *(suggestion-only)* | Flags ambiguous, double-barreled, leading or jargon-heavy questions and suggests clearer wording (or a split, which you apply in the source document) | Whether a sentence is leading is a language judgement |
| **Choice-list ordering** *(suggestion-only)* | Proposes a more logical option order — common answers first, themes adjacent, "Other"/"Refused" last | "Farming" belonging next to "Fishing" isn't a sortable property |
| **Enumerator instructions** *(suggestion-only)* | Drafts per-question field guidance (probing technique, common misunderstandings) as device `hint` text — only for questions with no author-written hint, which always wins | Anticipating how respondents misunderstand a question is survey-methodology judgement |

The four **suggestion-only** features never touch the form by themselves:
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
  deterministic name is therefore always the one in use. If you want a
  different name, rename it in the review panel — the tool deterministically
  rewrites every `${...}` reference so nothing dangles — rather than delegating
  naming to a model.
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
