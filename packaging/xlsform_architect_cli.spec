# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the XLSForm Architect command-line executable.

Build (from the project root, on Windows)::

    pip install -r requirements-dev.txt
    pyinstaller packaging/xlsform_architect_cli.spec

Produces ``dist/xlsform-architect.exe`` - a standalone CLI that needs no
Python installed on the target machine.  The knowledge YAML files, the
XLSForm template and the examples are bundled as data files.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

project_root = Path(SPECPATH).parent
pkg = project_root / "xlsform_architect"

datas = []
datas += [(str(p), "xlsform_architect/knowledge") for p in (pkg / "knowledge").glob("*.yaml")]
datas += [(str(p), "xlsform_architect/templates") for p in (pkg / "templates").glob("*.xlsx")]
datas += collect_data_files("xlsform_architect", includes=["examples/*"])

hiddenimports = ["openpyxl", "pandas", "docx", "fitz", "lxml", "yaml"]

block_cipher = None

a = Analysis(
    [str(pkg / "app" / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["streamlit"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="xlsform-architect",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
