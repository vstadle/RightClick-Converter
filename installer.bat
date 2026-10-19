@echo off
rem Installe RightClick-Converter et ajoute "Convertir en" au clic droit (sans droits admin).
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creation de l'environnement Python...
    py -3 -m venv .venv 2>nul || python -m venv .venv || goto :error
)
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -e . || goto :error
".venv\Scripts\python.exe" -m quickconvert install || goto :error
echo.
pause
exit /b 0

:error
echo.
echo Echec de l'installation (Python 3.10+ est-il installe ?).
pause
exit /b 1
