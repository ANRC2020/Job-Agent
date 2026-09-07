@echo off
setlocal
title Clover Installer

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 (
  echo.
  echo Clover could not finish installing. The error above explains what failed.
  echo This window will stay open so you can share the message.
  pause
  exit /b 1
)

exit /b 0
