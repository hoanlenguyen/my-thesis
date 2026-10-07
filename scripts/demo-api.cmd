@echo off
rem Local API for the demo's "Try it" page (http://localhost:3001/try). Keep this window open while using it.
cd /d "%~dp0.."
uv run --extra demo uvicorn hems.demo_api:app --port 8001
pause
