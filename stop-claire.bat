@echo off
title Claire AI - Stopping...
echo.
echo   Stopping Claire AI...
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0scripts\stop.ps1"

echo.
echo   Script selesai. Semua service telah dimatikan.
pause
