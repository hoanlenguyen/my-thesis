@echo off
rem Double-click to continue the design-iteration-9 run (configs\iteration9.json): the lean pipeline and the
rem final pipeline, interleaved per scenario on the exploratory factorial main set.
rem Safe to close this window, sleep or shut down at any time: finished runs are kept,
rem and the next start continues where it stopped (only the run in progress is repeated).
cd /d "%~dp0.."
uv run hems campaign run --plan configs\iteration9.json
echo.
pause
