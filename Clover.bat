@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\job-agent.exe" (
  ".venv\Scripts\job-agent.exe" launch
  goto :eof
)
echo Clover is not installed yet. Run install.bat first.
pause
