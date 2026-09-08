@echo off
setlocal
title Clover Uninstaller

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
if errorlevel 1 (
  echo.
  echo Clover could not finish uninstalling. The error above explains what failed.
  if not defined CI pause
  exit /b 1
)

echo.
if not defined CI pause
