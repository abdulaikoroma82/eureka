"""Streamlit app entry point for Hugging Face Spaces.

Hugging Face Spaces automatically detects and runs app.py or streamlit_app.py
for Streamlit applications. This file bridges to the XLSForm Studio UI.
"""

import sys
from pathlib import Path

# Ensure the package is importable
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Run the UI (automatically calls main() when executed as __main__)
import xlsform_studio.app.ui
