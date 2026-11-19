@echo off
REM Adds the Kokoro voice engine (smoother, more natural voices).
REM Downloads about 340 MB the first time a Kokoro voice is used.
title Install better Gipsy voices
cd /d "%~dp0"
call .venv\Scripts\activate.bat
echo Installing Kokoro into Gipsy's private Python environment ...
pip install "kokoro-onnx>=0.4" || goto :fail
echo.
echo Done. Now making sample clips so you can hear every voice ...
python voice_samples.py
pause
exit /b 0
:fail
echo Something went wrong. Copy the error above and send it to Claude.
pause
exit /b 1
