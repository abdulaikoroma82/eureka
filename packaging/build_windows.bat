@echo off
REM ===========================================================================
REM  Build the XLSForm Architect Windows executables.
REM  Run this from the project root in a Windows command prompt.
REM ===========================================================================

echo Creating virtual environment...
python -m venv .venv
call .venv\Scripts\activate.bat

echo Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements-dev.txt

echo Building CLI executable (dist\xlsform-architect.exe)...
pyinstaller packaging\xlsform_architect_cli.spec --noconfirm

echo.
echo ===========================================================================
echo  CLI build complete:  dist\xlsform-architect.exe
echo.
echo  To run the graphical (Streamlit) app on this machine instead, use:
echo     python run_ui.py
echo ===========================================================================
pause
