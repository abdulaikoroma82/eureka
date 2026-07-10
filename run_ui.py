"""Convenience launcher for the Streamlit UI.

Runs the XLSForm Architect web interface without needing to remember the
full ``streamlit run`` path.  Works from a source checkout and from a
PyInstaller/py2exe bundle.

Usage
-----
    python run_ui.py
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parent
    ui_path = project_root / "xlsform_architect" / "app" / "ui.py"

    # Ensure the package is importable.
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    try:
        from streamlit.web import cli as stcli
    except ImportError:
        print("Streamlit is not installed. Run: pip install streamlit", file=sys.stderr)
        return 1

    sys.argv = ["streamlit", "run", str(ui_path), "--server.headless=true"]
    return stcli.main()


if __name__ == "__main__":
    raise SystemExit(main())
