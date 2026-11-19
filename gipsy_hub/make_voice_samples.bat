@echo off
REM Makes a sample clip of every Gipsy voice and opens the folder.
REM Close the Gipsy Hub window first, or it will be slower.
title Gipsy voice samples
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python voice_samples.py
pause
