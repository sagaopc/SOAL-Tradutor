@echo off
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel%==0 (
  start "" pyw -3 "SOAL Tradutor.pyw"
  exit /b
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw "SOAL Tradutor.pyw"
  exit /b
)
echo Nao encontrei o Python. Instale o Python 3 em https://www.python.org/downloads/ ^(marque "Add python.exe to PATH"^) e tente de novo.
pause
