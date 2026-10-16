@echo off
rem Double-click to run or continue the Swiss-household (RAPT) evaluation (configs\rapt_ch.json).
rem Safe to close this window at any time: finished runs are kept and the next start continues.
cd /d "%~dp0.."
uv run hems campaign run --plan configs\rapt_ch.json
echo.
pause
