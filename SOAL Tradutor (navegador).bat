@echo off
title SOAL Tradutor (navegador)
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 run.py --navegador %*
) else (
  python run.py --navegador %*
)
if errorlevel 1 pause
