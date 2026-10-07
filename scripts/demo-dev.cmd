@echo off
rem Demo web app on http://localhost:3001 (start scripts\demo-api.cmd too for the "Try it" page).
cd /d "%~dp0..\demo"
pnpm dev --port 3001
pause
