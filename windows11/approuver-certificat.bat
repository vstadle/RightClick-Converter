@echo off
rem Approuve le certificat du menu Windows 11 de QuickConvert (une seule fois).
rem Clic droit > Executer en tant qu'administrateur.
net session >nul 2>&1
if errorlevel 1 (
    echo Ce script doit etre lance en administrateur :
    echo clic droit sur approuver-certificat.bat ^> Executer en tant qu'administrateur.
    pause
    exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0certificat.ps1"
pause
