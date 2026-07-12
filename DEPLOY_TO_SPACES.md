# Deploying XLSForm Studio to Hugging Face Spaces

Hugging Face Spaces is a free or low-cost hosting option for Streamlit applications with excellent built-in support for Python dependencies, environment variables, and persistent storage.

## Quick Start

### 1. Create a Hugging Face Space

1. Go to [huggingface.co/spaces](https://huggingface.co/spaces)
2. Click **Create new Space**
3. Fill in:
   - **Space name**: `xlsform-studio` (or your preferred name)
   - **License**: Select a license (e.g., MIT)
   - **Select the Space SDK**: Choose **Streamlit**
4. Click **Create Space**

### 2. Connect Your GitHub Repository

On the Space page, go to **Settings** → **Repository** and select your repository (`abdulaikoroma82/eureka`). This enables automatic syncing: every push to your designated branch updates the Space.

Alternatively, if you prefer manual control, skip this step and manage commits separately.

### 3. Configure Environment Variables (for AI features)

If you want to enable AI-assisted features (translation, logic resolution, semantic review), you'll need a DeepSeek API key.

1. Go to Space **Settings** → **Variables and secrets**
2. Add a new secret:
   - **Name**: `DEEPSEEK_API_KEY`
   - **Value**: Your DeepSeek API key from https://platform.deepseek.com/
3. Save

Without this variable, XLSForm Studio runs in fully offline, deterministic mode (no network calls, no external dependencies).

### 4. That's It!

The Space automatically:
- Clones your repo
- Installs dependencies from `requirements.txt`
- Runs `streamlit run app.py`
- Exposes the app at `https://huggingface.co/spaces/<your-username>/<space-name>`

## How It Works

### Session Isolation

XLSForm Studio v1.17.0+ includes built-in multi-user session isolation:

- Each browser session gets its own private temporary directory
- Uploaded files and generated outputs are isolated per session
- Stale session directories (>24 hours old) are automatically cleaned
- No shared state between concurrent users

### File Storage

- **Ephemeral** (default): Temporary files in `/tmp` are cleaned on container restart
- **Persistent** (optional): For permanent output storage, add a `--persistent-data-dir` volume

If you need persistent storage (e.g., to keep generated forms across container restarts), contact Hugging Face support or use a persistent Space.

## Configuration Details

### `app.py`

The root-level `app.py` is auto-detected by Spaces as the Streamlit entry point. It:

1. Ensures the project root is in `sys.path` for imports
2. Imports the main UI module
3. Streamlit automatically runs the UI's `main()` function

### `requirements.txt`

All dependencies are specified in the root `requirements.txt`:

```
openpyxl>=3.1
pandas>=2.0
python-docx>=1.1
PyMuPDF>=1.24
lxml>=5.0
PyYAML>=6.0
pyxform>=2.0
streamlit>=1.33
```

For AI features, add an optional dependency section (currently DeepSeek is lazy-loaded only when explicitly enabled).

### Container Limits

Hugging Face Spaces run on shared hardware with resource limits:

- **CPU**: Shared (no SLA for consistency)
- **Memory**: ~7-8 GB available
- **Disk**: ~50 GB available per Space
- **Timeout**: Scripts that don't produce output are restarted after ~48 hours

For production deployments with guaranteed resources, consider:
- **Render** or **Railway** (affordable, auto-scaling)
- **Fly.io** (global edge deployment)
- **AWS/GCP/Azure** (full control, highest cost)

## Updating Your Space

### Automatic Updates (if connected to GitHub)

- Push changes to your designated branch
- Spaces automatically pulls and restarts
- Live within ~30 seconds

### Manual Updates (if not connected)

1. Clone the Space as a Git repo: `git clone https://huggingface.co/spaces/<username>/<space-name>`
2. Pull latest changes from your GitHub repo
3. Push to the Space's repo: `git push`

## Monitoring and Logs

- **App Output**: View live Streamlit output in the Space's **App logs** tab
- **Build Logs**: Check build status and dependency installation in the **Build logs** tab
- **Errors**: Streamlit errors are displayed in the browser and in App logs

## Troubleshooting

### "Module not found" errors

Ensure `requirements.txt` includes all dependencies. Common missing packages:
- `streamlit>=1.33` — the UI framework
- `openpyxl>=3.1` — XLS/XLSX parsing
- `python-docx>=1.1` — DOCX parsing
- `PyMuPDF>=1.24` — PDF parsing
- `lxml>=5.0` — XML/XPath support
- `pandas>=2.0` — data processing
- `PyYAML>=6.0` — configuration parsing
- `pyxform>=2.0` — XLSForm validation

### Slow startup

Streamlit containers take 20–60 seconds to start. This is normal. If startup consistently fails, check:
1. **Build logs** for dependency conflicts
2. **App logs** for runtime errors
3. Space's available disk space and memory

### "Permission denied" on output files

Session directories are created with permissive permissions. If you hit permission errors:
1. Check Streamlit console for file-system warnings
2. Ensure `/tmp` has sufficient free space
3. Restart the Space (via Settings → Restart)

### Output files not persisting

By default, temporary files are cleaned up on container restart. This is intentional for multi-user isolation. If you need persistent output:
- Use Hugging Face's **persistent storage** (Space Settings → Storage)
- Or switch to a persistent hosting platform (Render, Railway, Fly.io)

## Next Steps

Once your Space is live:

1. **Test the upload flow**: Upload a sample questionnaire (DOCX, XLSX, PDF, CSV, or JSON)
2. **Test platform selection**: Try Kobo, SurveyCTO, ODK, Ona, CommCare
3. **Test output download**: Generate an XLSForm and download the ZIP
4. **Enable AI** (optional): Add DEEPSEEK_API_KEY and test AI features (translation, logic resolution, semantic review)
5. **Share the link**: Your app is publicly accessible at `https://huggingface.co/spaces/<username>/<space-name>`

## Support

- **Hugging Face Spaces docs**: https://huggingface.co/docs/hub/spaces
- **Streamlit docs**: https://docs.streamlit.io/
- **XLSForm Studio issues**: https://github.com/abdulaikoroma82/eureka/issues
