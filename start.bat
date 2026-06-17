@echo off
SETLOCAL
title IT Help

echo =============================================
echo   IT Help - Workstation Management Suite
echo =============================================
echo.

:: Check Python
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python 3.11+ not found in PATH.
    echo Download from https://python.org
    pause & exit /b 1
)

:: Install dependencies if needed
python -c "import fastapi" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Installing dependencies...
    python -m pip install -r requirements.txt
    if %ERRORLEVEL% NEQ 0 ( echo ERROR: pip install failed. & pause & exit /b 1 )
)

:: Get local IP for display
for /f "tokens=4" %%i in ('route print 0.0.0.0 ^| findstr 0.0.0.0') do set LOCAL_IP=%%i

echo.
echo  Starting server...
echo  Local:   http://localhost:8080
echo  Network: http://%LOCAL_IP%:8080
echo.
echo  Open the URL above in any browser.
echo  On Chrome/Edge: click the install icon in the address bar to install as an app.
echo.
echo  Press Ctrl+C to stop.
echo =============================================
echo.

python server.py
pause
