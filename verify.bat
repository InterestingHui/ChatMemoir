@echo off
chcp 65001 >nul

REM Headless verifier launcher. Self-elevates via UAC (one Yes click),
REM runs verify-pipeline.py, captures all output to verify-pipeline.log.

net session >nul 2>&1
if errorLevel 1 (
    echo Requesting admin privileges, click Yes on UAC...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Running headless pipeline verifier...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "cd '%~dp0'; python.exe verify-pipeline.py 2>&1 | Tee-Object -FilePath '%~dp0verify-pipeline.console.log'"
echo.
echo Done. Logs:
echo   %~dp0verify-pipeline.log         (structured log)
echo   %~dp0verify-pipeline.console.log (full console capture)
echo.
pause
