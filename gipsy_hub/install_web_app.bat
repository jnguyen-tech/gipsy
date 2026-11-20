@echo off
REM Downloads the newest web version of the Gipsy app into gipsy_hub\web.
REM The hub then hands it to Safari on your iPhone/iPad (Add to Home Screen).
REM Run it again any time to update. Restart the hub afterwards.
cd /d "%~dp0"
set URL=https://github.com/jnguyen-tech/gipsy/releases/download/web-app/Gipsy-Web.zip
echo Downloading the Gipsy web app ...
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest -UseBasicParsing '%URL%' -OutFile Gipsy-Web.zip" || goto :fail
if exist web rmdir /s /q web
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; Expand-Archive Gipsy-Web.zip -DestinationPath web" || goto :fail
del Gipsy-Web.zip
echo.
echo Done. Restart the hub (close its window, then run start_hub.bat).
echo Then follow "Use Gipsy on iPhone and iPad" in docs\WEB-APP.md.
pause
exit /b 0
:fail
echo Download failed. Check the "Gipsy web app" run on the repo's Actions tab
echo finished, or download Gipsy-Web.zip by hand and unzip it into gipsy_hub\web.
pause
exit /b 1
