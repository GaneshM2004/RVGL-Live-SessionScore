@echo off
REM ============================================================
REM  RVGL Live Scoreboard Launcher
REM  Starts the client uploader silently, launches RVGL,
REM  and cleans up the uploader when the game exits.
REM ============================================================

echo [LiveScore] Starting client uploader in background...
start "" /B pythonw client_uploader.py

echo [LiveScore] Launching RVGL...
start "" /WAIT rvgl.exe

echo [LiveScore] Game closed. Shutting down uploader...
taskkill /F /IM pythonw.exe >nul 2>&1

echo [LiveScore] Done. Goodbye!
timeout /t 2 >nul
