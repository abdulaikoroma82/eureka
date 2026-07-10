# Packaging XLSForm Architect for Windows

Two distribution options are supported.

## 1. Command-line executable (`.exe`) — fully standalone

The CLI packages cleanly with [PyInstaller](https://pyinstaller.org) because it
has no web-server runtime.

```bat
:: from the project root, on Windows
pip install -r requirements-dev.txt
pyinstaller packaging\xlsform_architect_cli.spec
```

This produces `dist\xlsform-architect.exe`. Copy it anywhere — it needs **no
Python** on the target machine:

```bat
xlsform-architect.exe survey.docx --category imam --output C:\forms
```

The one-click `packaging\build_windows.bat` does all of the above.

## 2. Graphical (Streamlit) app

Streamlit apps depend on a live web server and its data files, which PyInstaller
does not bundle reliably. The recommended approach on an internal machine or
server is a small self-contained Python environment:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run_ui.py
```

`run_ui.py` launches the browser UI (`http://localhost:8501`). To ship this as a
double-clickable launcher, save the following as `XLSForm Architect.bat` next to
the project:

```bat
@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python run_ui.py
```

### Notes
* The knowledge YAML files, XLSForm template and examples are bundled as data
  files in the CLI spec (`datas`), so program rules travel with the executable.
* No Claude / OpenAI / cloud service is contacted at any point — the tool runs
  entirely offline.
