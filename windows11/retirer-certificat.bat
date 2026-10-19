@echo off
rem Retire l'approbation du certificat du menu Windows 11 de RightClick-Converter.
rem Clic droit > Executer en tant qu'administrateur.
net session >nul 2>&1
if errorlevel 1 (
    echo Ce script doit etre lance en administrateur :
    echo clic droit sur retirer-certificat.bat ^> Executer en tant qu'administrateur.
    pause
    exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0certificat.ps1" -Retirer
pause
