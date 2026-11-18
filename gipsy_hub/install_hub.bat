@echo off
REM One-time setup for Gipsy Hub. Needs Python 3.11+ from python.org
REM (tick "Add python.exe to PATH" when installing).
cd /d "%~dp0"
echo Creating a private Python environment in .venv ...
python -m venv .venv || goto :fail
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || goto :fail
echo.
echo Allowing phones on your private network to reach port 8765 ...
echo (Windows may ask for admin permission. Say yes.)
powershell -Command "Start-Process netsh -Verb RunAs -ArgumentList 'advfirewall firewall add rule name=\"Gipsy Hub\" dir=in action=allow protocol=TCP localport=8765 profile=private'"
echo.
echo Done. Double-click start_hub.bat to run Gipsy Hub.
pause
exit /b 0
:fail
echo Something went wrong. Copy the error above and send it to Claude.
pause
exit /b 1
