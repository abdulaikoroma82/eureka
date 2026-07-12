# XLSForm Studio - Streamlit web UI container.
#
# Builds an image that serves the graphical app on $PORT (defaults to 8501),
# suitable for any container-based host (Render, Railway, Fly.io, a plain
# VPS running Docker, ...). For a CLI-only / CI container instead, see the
# minimal snippet in README.md under "Deployment".
#
# Build:  docker build -t xlsform-studio-web .
# Run:    docker run --rm -p 8501:8501 xlsform-studio-web
#         docker run --rm -p 8501:8501 -e DEEPSEEK_API_KEY=sk-... xlsform-studio-web
#
# No AI network calls happen unless DEEPSEEK_API_KEY is set - the container
# is airtight offline by default even when publicly hosted.

FROM python:3.11-slim

WORKDIR /app

# System libraries PyMuPDF (PDF parsing/export) needs at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN pip install --no-cache-dir .

# Every browser session gets its own tempfile.mkdtemp() output directory
# (see xlsform_studio/app/ui.py:_session_output_dir) - nothing here needs
# to be a persistent volume; a container restart losing /tmp is fine.
ENV XLSFS_OUTPUT_DIR=/tmp/xlsform_studio_output
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT','8501') + '/_stcore/health', timeout=3)" || exit 1

CMD ["python", "run_ui.py"]
