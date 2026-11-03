@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\pythonw.exe" (
  start "" "%~dp0.venv\Scripts\pythonw.exe" -m codex_relocate --state-dir "%~dp0local-state" gui
) else (
  start "" pyw -3 -m codex_relocate --state-dir "%~dp0local-state" gui
)
