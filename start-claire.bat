@echo off
title Claire AI — Starting...
echo.
echo   Starting Claire AI...
echo   Please wait, this may take a moment.
echo.

powershell -ExecutionPolicy Bypass -NoExit -File "%~dp0scripts\start.ps1"

echo.
echo   Script selesai. Kalau ada error, baca pesan di atas.
pause
