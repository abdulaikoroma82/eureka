# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the XLSForm Studio command-line executable.

Build (from the project root, on Windows)::

    pip install -r requirements-dev.txt
    pyinstaller packaging/xlsform_studio_cli.spec

Produces ``dist/xlsform-studio.exe`` - a standalone CLI that needs no
Python installed on the target machine.  The knowledge YAML files, the
XLSForm template and the examples are bundled as data files.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

project_root = Path(SPECPATH).parent
pkg = project_root / "xlsform_studio"

datas = []
datas += [(str(p), "xlsform_studio/knowledge") for p in (pkg / "knowledge").glob("*.yaml")]
datas += [(str(p), "xlsform_studio/templates") for p in (pkg / "templates").glob("*.xlsx")]
datas += collect_data_files("xlsform_studio", includes=["examples/*"])
# pyxform ships template/data files that must travel with the executable.
datas += collect_data_files("pyxform")

hiddenimports = ["openpyxl", "pandas", "docx", "fitz", "lxml", "yaml", "pyxform"]

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
    name="xlsform-studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
