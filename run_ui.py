"""Convenience launcher for the Streamlit UI.

Runs the XLSForm Studio web interface without needing to remember the
full ``streamlit run`` path.  Works from a source checkout and from a
PyInstaller/py2exe bundle, and unattended in a container: it binds to all
interfaces and honours the ``$PORT`` environment variable most hosting
platforms (Render, Railway, Fly.io, ...) inject automatically, so the same
launcher works locally and in a hosted deployment with no flags.

Usage
-----
    python run_ui.py                  # local: http://localhost:8501
    PORT=10000 python run_ui.py       # hosted: binds 0.0.0.0:10000
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parent
    ui_path = project_root / "xlsform_studio" / "app" / "ui.py"

    # Ensure the package is importable.
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    try:
        from streamlit.web import cli as stcli
    except ImportError:
        print("Streamlit is not installed. Run: pip install streamlit", file=sys.stderr)
        return 1

    port = os.environ.get("PORT", "8501")
    sys.argv = ["streamlit", "run", str(ui_path), "--server.headless=true",
                f"--server.port={port}", "--server.address=0.0.0.0"]
    return stcli.main()


if __name__ == "__main__":
    raise SystemExit(main())
