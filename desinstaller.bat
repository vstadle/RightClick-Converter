@echo off
rem Retire "Convertir en" du clic droit. Le dossier peut ensuite etre supprime.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m quickconvert uninstall
pause
