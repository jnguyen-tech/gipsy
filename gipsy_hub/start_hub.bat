@echo off
title Gipsy Hub
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python gipsy_hub.py
pause
