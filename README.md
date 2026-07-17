# XLSForm Studio

**An AI-first survey engineering platform that drafts, validates, documents,
and quality-assures questionnaires for the entire XLSForm ecosystem
(KoboToolbox, SurveyCTO, ODK, Ona, CommCare).**

Drop in a questionnaire of **any kind** — Word, Excel, PDF, CSV or JSON — and
get back a complete, validated XLSForm package: the spreadsheet plus a data
dictionary, QA report, assumption log, logic map, survey-design score and
version history. It applies the **standard rules of the XLSForm
specification** and is not tied to any survey domain.

> 🟢 **New here / non-technical?** Start with the plain-language
> [Getting Started guide](docs/GETTING_STARTED.md) — no coding needed.

---

## How the AI is used — two distinct roles

The model is used in two roles with **opposite requirements**. This is the
one thing to be clear on:

| Role | Required? | What it does |
| --- | --- | --- |
| **AI-assisted authoring** | **Required** | The model **drafts every field** of the form (types, names, labels, logic, constraints, choice lists). A run needs a valid `DEEPSEEK_API_KEY`; there is no offline authoring fallback. Deterministic rules bracket it — the parser lays out the scaffold, and the standards enforcer + validators check the draft. You **review and edit** the draft before download. |
| **AI enrichment** | **Optional** | Extra passes (translation, quality review, finding explanations, advisory suggestions) that **refine** the authored draft. Off by default, enabled per-feature, and **fail open** — a failure skips just that pass and leaves the form intact. They never re-author the form. |

Full detail: **[AI authoring & enrichment](docs/ai.md)**.

---

## Why it exists

Hand-coding XLSForms is slow and error-prone: mistyped variable names, broken
`relevant` references, missing choice lists, inconsistent constraints. XLSForm
Studio standardises that work and catches the errors before deployment.

---

## Quickstart

Requires **Python 3.11+** (3.12+ recommended) and a `DEEPSEEK_API_KEY`.

```bash
git clone <repo-url> && cd eureka
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e .                                     # gives you the `xlsform-studio` command
export DEEPSEEK_API_KEY="sk-..."                     # https://platform.deepseek.com

# Graphical app:
python run_ui.py

# Command line:
xlsform-studio survey.docx --target kobo -o ./out
```

More: **[Usage & API](docs/api.md)** (all CLI flags, the library API, input
formats, JSON schema).

---

## What you get

- **AI-drafted, human-reviewed forms** — every authored field is editable
  before export, with a confidence badge on the ambiguous ones.
- **A deterministic validator** that catches broken references, dead
  comparisons, unbalanced groups, choice-code errors, unsafe identifiers, and
  runs pyxform for a near-authoritative deep check — see
  [Validation & quality](docs/validation.md).
- **A Survey Design Score** — a deterministic, ten-dimension methodological
  assessment (question order, recall consistency, measurement validity, …)
  that moves the tool from form *generation* into survey *methodology
  assistance*.
- **A full documentation package** — data dictionary, QA report, logic map,
  enumerator guide, collection plan, printable instrument, and a provenance
  sidecar that enables **round-trip editing** (edit the XLSForm, re-import it,
  keep every field's confidence).
- **An interview simulator** that runs the form's skip/constraint/calculation
  logic so you can see it behave before deploying.
- **Platform-aware export** in each target's column dialect, with an honest
  per-platform compatibility matrix.

---

## Documentation

| Guide | What's in it |
| --- | --- |
| [Getting Started](docs/GETTING_STARTED.md) | Plain-language walkthrough, no coding needed. |
| [Usage & API](docs/api.md) | Graphical app, full CLI reference, the library API, input formats, JSON input schema. |
| [Architecture](docs/architecture.md) | The pipeline, project layout, the AI-draft review panel, the output package, reverse-engineering and round-trip editing. |
| [AI authoring & enrichment](docs/ai.md) | The two AI roles in depth, every enrichment feature, what stays deterministic, setup, safety and cost design. |
| [Validation & quality](docs/validation.md) | What the deterministic layer owns, the validation layers, confidence levels, the Survey Design Score, platform standards, and the interview simulator. |
| [Extending the rules](docs/extending.md) | Editing the YAML rule packs and adding domain packs — no code changes. |
| [Deployment & operations](docs/deployment.md) | Hosting the app, Docker/CI, configuration knobs, error recovery, troubleshooting. |
| [Developer guide](docs/developer-guide.md) | Running the test suite and packaging a Windows build. |
| [Roadmap](docs/ROADMAP.md) | Capability status for every module. |

---

## License

MIT.
