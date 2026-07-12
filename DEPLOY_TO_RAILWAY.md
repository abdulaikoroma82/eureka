# Deploying XLSForm Studio to Railway

Railway builds directly from the repo's `Dockerfile`, so no extra buildpack configuration is needed — the same container that works locally and on any other Docker host works here unmodified.

## Quick Start

### 1. Create a Railway Project

1. Go to [railway.app](https://railway.app) and sign in
2. Click **New Project** → **Deploy from GitHub repo**
3. Select `abdulaikoroma82/eureka`
4. Railway detects the `Dockerfile` at the repo root and builds from it automatically (confirmed via `railway.json`, which pins `builder: DOCKERFILE`)

### 2. Set the Branch to Deploy

In the service's **Settings** → **Source**, set the branch to whichever branch you want live (e.g. `main` after merging, or a feature branch for a preview deploy).

### 3. Configure Environment Variables (for AI features)

Only needed if you want AI-assisted translation, logic resolution, and semantic review:

1. Go to the service's **Variables** tab
2. Add: `DEEPSEEK_API_KEY` = your key from https://platform.deepseek.com/

Without it, the app runs fully offline/deterministic — no network calls.

Railway automatically injects `PORT`; `run_ui.py` already reads it and binds `0.0.0.0`, so no manual port configuration is required.

### 4. Generate a Public Domain

In **Settings** → **Networking**, click **Generate Domain**. Railway gives you a URL like `https://eureka-production-xxxx.up.railway.app`.

### 5. Deploy

Railway auto-deploys on every push to the configured branch. Watch progress under the **Deployments** tab; build logs and runtime logs are both visible there.

## What's Already in Place

- **Dockerfile** — builds the image, installs system deps (`libgl1` for PyMuPDF), sets `XLSFS_OUTPUT_DIR=/tmp/xlsform_studio_output`, and runs `python run_ui.py`.
- **run_ui.py** — reads `$PORT` (Railway sets this at runtime) and binds `0.0.0.0`, which Railway's edge proxy requires.
- **railway.json** — pins the Dockerfile builder explicitly and configures a health check against Streamlit's `/_stcore/health` endpoint, with automatic restart on failure.
- **railpack.json** — fallback config for Railway's Railpack builder (see note below). Sets `libgl1` as an apt package and `python run_ui.py` as the start command.
- **Session isolation** — each browser session gets its own `tempfile.mkdtemp()` output directory (`xlsform_studio/app/ui.py:_session_output_dir`), with a 24h auto-sweep of stale directories. Safe for concurrent multi-user traffic out of the box.

### Known issue: Railway may ignore the Dockerfile builder

As of mid-2026, Railway has an active platform bug where its default builder (Railpack) sometimes ignores `railway.json`'s `"builder": "DOCKERFILE"` setting — even on a freshly created service — and falls back to auto-detecting a plain Python app, which then fails with `No start command detected` (see [Railway Central Station reports](https://station.railway.com/questions/railpack-ignoring-railway-json-dockerfil-a3c09f1b)).

If your build log shows a `Railpack` banner instead of `FROM python:3.11-slim` / `apt-get` steps, this bug is active for your service. `railpack.json` at the repo root is the workaround: it gives Railpack its own start command and apt package (`libgl1`) so the build succeeds even without switching to the Dockerfile builder. No action needed on your end beyond redeploying — Railway will pick up `railpack.json` automatically.

If Railway fixes the underlying bug later and your service switches back to the Dockerfile builder, `railpack.json` is simply unused and harmless to leave in place.

## Storage Notes

Railway's filesystem is ephemeral per deployment — a redeploy or restart wipes `/tmp`. That's fine here: generated output lives in per-session temp directories by design, not meant to persist across restarts. If you need durable storage (e.g., an audit trail of every generated form), attach a Railway volume or push outputs to external storage (S3-compatible bucket) — neither is set up currently.

## Resource Sizing

Railway's default plan gives shared CPU and a memory ceiling per service (check current limits in your plan under **Usage**). PyMuPDF (PDF parsing) and pandas are the heaviest dependencies; if you see OOM kills on large PDF uploads, bump the service's memory limit in **Settings** → **Resources**.

## Troubleshooting

- **Build fails on `libgl1` install**: Railway's Docker builder should handle `apt-get` fine; if it fails, check build logs for a mirror/network issue and retry.
- **App builds but health check fails**: confirm the service actually listens on `$PORT` — `run_ui.py` should already do this. Check runtime logs for a stack trace on startup.
- **"Application failed to respond"**: usually means the app crashed after boot. Check **Deployments** → **View Logs** for the Python traceback.
- **AI features not working**: verify `DEEPSEEK_API_KEY` is set in **Variables** and that you toggled AI on in the app's sidebar — both are required.

## Removing the Hugging Face Spaces Setup

`app.py`, `.streamlit/config.toml`, and `DEPLOY_TO_SPACES.md` from the earlier Spaces setup are harmless left in place — Railway ignores them and only uses the Dockerfile. Let me know if you'd like them removed instead of just unused.
