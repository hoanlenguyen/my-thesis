@echo off
rem Double-click to run or continue the pre-registered Q2 confirmation (docs\preregistration_q2.md).
rem Safe to close this window at any time: finished runs are kept and the next start continues.
cd /d "%~dp0.."
uv run hems campaign run --plan configs\confirmation_q2.json
echo.
pause
