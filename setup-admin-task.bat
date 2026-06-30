@echo off
chcp 65001 >nul

REM Double-click entry point. Self-elevates via UAC, then runs the PowerShell setup.
REM One UAC "Yes" click required - unavoidable for admin privilege grant on Windows.

net session >nul 2>&1
if errorLevel 1 (
    echo Requesting admin privileges, click Yes on UAC...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-admin-task.ps1"
echo.
pause
