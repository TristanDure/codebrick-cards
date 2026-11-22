@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-study.ps1" %*
set "study_exit=%errorlevel%"
if not "%study_exit%"=="0" pause
exit /b %study_exit%
