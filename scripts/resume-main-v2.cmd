@echo off
rem Double-click to continue the exploratory run on the factorial main set (configs\main_v2.json).
rem Safe to close this window, sleep or shut down at any time: finished runs are kept,
rem and the next start continues where it stopped (only the run in progress is repeated).
cd /d "%~dp0.."
uv run hems campaign run --plan configs\main_v2.json
echo.
pause
