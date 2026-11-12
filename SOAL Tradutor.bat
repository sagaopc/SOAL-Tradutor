@echo off
title SOAL Tradutor
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 run.py %*
) else (
  python run.py %*
)
if errorlevel 1 (
  echo.
  echo Nao foi possivel iniciar. Instale o Python 3 em https://www.python.org/downloads/ ^(marque "Add python.exe to PATH"^) e tente de novo.
  pause
)
