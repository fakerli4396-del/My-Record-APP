@echo off
cd /d "%~dp0"
python -m unittest discover -v
if errorlevel 1 exit /b %errorlevel%
node --check ui.js
if errorlevel 1 exit /b %errorlevel%
node --test
exit /b %errorlevel%
