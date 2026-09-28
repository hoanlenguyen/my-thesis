@echo off
rem Double-click to see how far the thesis evaluation has got.
cd /d "%~dp0.."
uv run hems campaign status --plan configs\full_evaluation.json
echo.
pause
