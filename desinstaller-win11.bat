@echo off
rem Retire le menu Windows 11 (le menu classique de installer.bat reste en place).
cd /d "%~dp0"
".venv\Scripts\python.exe" -m quickconvert uninstall-win11
pause
