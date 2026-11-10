@echo off
cd /d "%~dp0"
python -c "import sys,struct; sys.exit(0 if sys.version_info[:2] == (3,14) and struct.calcsize('P') == 8 else 1)"
if errorlevel 1 (
  echo Python 3.14 x64 is required. Install it and run Setup.cmd again.
  goto fail
)
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install --only-binary=:all: --index-url https://pypi.org/simple -r requirements.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 goto fail
echo Ready. Open Start.cmd.
pause
exit /b 0
:fail
echo Setup failed. See the error above.
pause
exit /b 1
