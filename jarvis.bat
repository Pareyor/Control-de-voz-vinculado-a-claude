@echo off
title Jarvis
cd /d "%~dp0"
".venv\Scripts\python.exe" jarvis.py %*
pause
