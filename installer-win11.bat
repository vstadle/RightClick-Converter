@echo off
rem Ajoute "Convertir en" au premier menu du clic droit de Windows 11 (sans droits admin).
rem A lancer apres installer.bat. La premiere fois, il demande d'approuver un certificat.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Lancer d'abord installer.bat.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m quickconvert install-win11
echo.
pause
