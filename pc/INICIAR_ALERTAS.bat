@echo off
chcp 65001 >nul
title MATRIX - vigilante de partidos
cd /d "%~dp0"

echo.
echo  ============================================================
echo    MATRIX - vigilante de partidos
echo  ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo  No encuentro Python en esta PC.
    echo  Instalalo desde https://www.python.org/downloads/
    echo  y marca "Add Python to PATH" durante la instalacion.
    echo.
    pause
    exit /b 1
)

python -c "import openpyxl" >nul 2>&1
if errorlevel 1 (
    echo  Falta la libreria openpyxl. La instalo...
    python -m pip install openpyxl
    echo.
)

python vigilante.py

echo.
echo  La vigilancia se detuvo.
pause
