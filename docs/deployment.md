[← Documentation index](../README.md#documentation)

# Deployment & operations

## Deployment

The tool has no database and no cross-session server state — every browser
session that hits the Streamlit UI gets its own private temp directory
(`tempfile.mkdtemp()`, swept automatically after 24h), so one visitor's
survey content is never written where another visitor's session could see
it. That makes "host it online for a team" a matter of running the existing
app on a public URL, not a rearchitecture.

**Docker / CI (headless, CLI only).** A minimal container needs Python
3.11+ and the package:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .
ENTRYPOINT ["xlsform-studio"]
```

```bash
docker build -t xlsform-studio .
# Authoring is AI-first, so the key (and egress to the DeepSeek API) is required:
docker run --rm -e DEEPSEEK_API_KEY=sk-... -v "$PWD:/data" \
    xlsform-studio /data/survey.docx -o /data/out
```

In a CI pipeline, run `xlsform-studio survey.docx -o build/` as a build step
and check its exit code: `0` means the form validated, `1` means validation
found errors, `2` means the run could not start (missing/rejected key, file
too large, unsupported format) — see [Usage](api.md). The run needs network
egress to the DeepSeek API to author the form; everything after authoring
(standards enforcement, validation, export, all documentation) is
deterministic and offline.

**Server (Streamlit UI).** The repo root [`Dockerfile`](../Dockerfile) builds
and serves the graphical app:

```bash
docker build -t xlsform-studio-web .
docker run --rm -p 8501:8501 xlsform-studio-web
# with AI enabled for every visitor, using your own key/budget:
docker run --rm -p 8501:8501 -e DEEPSEEK_API_KEY=sk-... xlsform-studio-web
```

It respects `$PORT` (so it drops into any container platform's expected
contract) and includes a Streamlit health-check endpoint
(`/_stcore/health`). Locally, `python run_ui.py` does the same without
Docker. The app is stateless per session, so no special session affinity
is needed beyond what Streamlit itself requires — you can run more than
one replica behind a load balancer.

**Where to host it.** Any platform that runs an arbitrary Docker container
on a public URL works; roughly in order of setup effort:

| Platform | Why you'd pick it |
| --- | --- |
| **Render** / **Railway** | Point at this repo, it detects the `Dockerfile`, builds, and gives you a URL with HTTPS - least setup for a small team. Free/cheap tiers exist but sleep on inactivity; a paid tier keeps it always-on. |
| **Fly.io** | Similar simplicity with more control over region/scaling; needs their CLI once to `fly launch`. |
| **A plain VPS** (DigitalOcean, a Hetzner box, EC2) | Full control, predictable flat cost, but you own patching/updates/TLS (`docker run` behind Caddy or nginx for free auto-HTTPS is the least-effort combo). |
| **Streamlit Community Cloud** | Purpose-built for Streamlit apps and genuinely the least effort of all, but requires a public GitHub repo (or their paid tier for private) and gives you the least infrastructure control. |

Whichever you pick, set `DEEPSEEK_API_KEY` as a platform secret (never
commit it) if you want AI features on for every visitor rather than
requiring each person to supply their own key.

**Configuration knobs** (all optional; the tool runs with sane defaults if
none are set):

| Variable | Purpose |
| --- | --- |
| `DEEPSEEK_API_KEY` | **Required.** The model drafts every form; a run fails without a valid key (there is no offline authoring fallback). Also powers the optional enrichment passes. |
| `XLSFS_OUTPUT_DIR` | Override the default output directory. |
| `XLSFS_MAX_INPUT_MB` | Maximum accepted upload/input size in MB (default `25`); a larger file is rejected before parsing, so one huge upload can't exhaust memory on a shared deployment. |
| `XLSFS_DEEPSEEK_BASE_URL` / `XLSFS_DEEPSEEK_MODEL` | Point the AI layer at a different DeepSeek-compatible endpoint/model. |
| `XLSFS_AUTHORING` | Internal seam only. `deterministic` selects the legacy rule-engine compiler (no key, no network) — used by the test suite, never a product mode. |
| `XLSFORM_STUDIO_LOG_LEVEL` | Diagnostic log verbosity for the Streamlit UI (`DEBUG`/`INFO`/`WARNING`/`ERROR`); the CLI uses `--log-level` instead. |

**Error recovery.** Steps degrade independently rather than taking the whole
run down:
- A parser failure on one file doesn't affect other files in a batch —
  each `xlsform-studio` invocation is one process, one exit code.
- **Authoring** requires the model: if the key is missing or rejected the run
  stops early with a clear message (a rejected key reports "DeepSeek rejected
  the API key"), rather than silently producing a half-formed result.
- Every **optional enrichment** pass, by contrast, fails open: a network
  error, malformed response or rate-limit skips just that feature, logs an
  `[AI] ...` note in the assumption log, and leaves the authored form intact.
- Validation errors are reported, not thrown — the XLSForm and full
  documentation package are still written even when the form is invalid,
  so you always have something to inspect and fix.

---

---

## Troubleshooting

**"A DeepSeek API key is required" / "DeepSeek rejected the API key".**
Authoring is AI-first — the model drafts every field — so a run needs a
valid `DEEPSEEK_API_KEY`. The first message means no key is configured; the
second means the key was reached but refused (wrong key, or out of quota).
There is no offline authoring mode in the shipped product (the
`XLSFS_AUTHORING=deterministic` seam exists only for the test suite).

**"AI enrichment was skipped."**
An *optional enrichment* pass (translation, quality review, a suggestion
pass, …) was requested but couldn't run — the API was unreachable, returned
something unexpected, or the form exceeds the 2,000-question enrichment
ceiling. The authored form and its documentation are complete and unaffected;
only the extra annotation is missing. Re-run later to add it.

**The AI API is down / rate-limited / times out mid-run.**
Enrichment passes fail open — each one independently skips and logs why in
the assumption log, and the authored form still finishes. If the *authoring*
call itself can't reach the API, the run reports the failure rather than
guessing; re-run when the API is reachable.

**A form with 500+ questions feels slow.**
The deterministic pipeline scales roughly linearly with question and
choice-list count and has been used well past this size, but very large
choice lists (thousands of options) will slow the consistency validator's
pairwise near-duplicate check the most; if that becomes a bottleneck,
disable AI features (they add the most latency per question) and profile
which validator is dominant before assuming it's the AI layer.

**"How do I trust an AI suggestion?"**
You don't have to — every AI mutation is validated deterministically at
apply time (see [AI authoring & enrichment](ai.md)),
advisory suggestions are never applied without explicit accept, and every
applied change is tagged "AI-suggested" in the assumption log with the
original value preserved. Run `xlsform-studio ... --log-level DEBUG` to
see exactly which features ran and what each one returned.

**I need to see what a run actually did, not just the output.**
Pass `--log-level DEBUG` (CLI) or set `XLSFORM_STUDIO_LOG_LEVEL=DEBUG`
before `streamlit run` (UI). This traces every AI feature's run/skip
decision, every network call's timing and outcome, and every AI
suggestion's accept/apply/reject outcome — without ever printing prompt
content or the API key.

**Where did my file go?**
Every run writes into a timestamped subfolder of the output directory
(`<form_id>_<YYYYMMDD_HHMMSS>/`), so re-running never overwrites a
previous package. `version_history.json` at the output root is the
append-only index across runs.

---
