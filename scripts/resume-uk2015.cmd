@echo off
rem Double-click to run or continue the UK 2015 appendix set (configs\uk2015.json).
rem Safe to close this window at any time: finished runs are kept and the next start continues.
cd /d "%~dp0.."
uv run hems campaign run --plan configs\uk2015.json
echo.
pause
