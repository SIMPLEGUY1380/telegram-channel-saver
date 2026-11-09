@echo off
setlocal
cd /d "%~dp0"

set "LOGFILE=%~dp0temp\reddit_automation.log"
if not exist "%~dp0temp" mkdir "%~dp0temp"

echo ======================================================== >> "%LOGFILE%"
echo [%date% %time%] Starting Reddit-to-Telegram automation check >> "%LOGFILE%"

"%~dp0venv\Scripts\python.exe" -m src.reddit_scheduler --once >> "%LOGFILE%" 2>&1

echo [%date% %time%] Check completed with exit code %ERRORLEVEL% >> "%LOGFILE%"
echo ======================================================== >> "%LOGFILE%"
endlocal
