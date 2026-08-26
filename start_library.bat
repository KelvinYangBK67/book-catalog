@echo off
setlocal
cd /d "%~dp0"

set "LIBRARY_PORT=17321"
set "LIBRARY_URL=http://127.0.0.1:%LIBRARY_PORT%"
set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
set "OPEN_BROWSER=1"

if /I "%~1"=="--no-browser" set "OPEN_BROWSER=0"

title Paper Library
echo.
echo   Paper Library - local book manager
echo   ==================================
echo.

if exist "%VENV_PYTHON%" goto environment_ready

echo [First run] Creating the private Python environment...
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 goto create_with_py

:try_python
python -c "import sys" >nul 2>nul
if errorlevel 1 goto no_python
python -m venv ".venv"
if errorlevel 1 goto setup_failed
goto environment_ready

:create_with_py
py -3 -m venv ".venv"
if errorlevel 1 goto setup_failed

:environment_ready
"%VENV_PYTHON%" -c "import fastapi, uvicorn" >nul 2>nul
if not errorlevel 1 goto dependencies_ready

echo [First run] Installing required packages. Please wait...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto setup_failed

:dependencies_ready
netstat -ano -p tcp | findstr /R /C:":%LIBRARY_PORT% .*LISTENING" >nul
if not errorlevel 1 goto port_in_use

if /I "%~1"=="--check" goto check_ok

echo [Starting] The browser will open at %LIBRARY_URL%
echo [Stopping] Close this window or press Ctrl+C.
echo.

if "%OPEN_BROWSER%"=="1" start "" /B powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Milliseconds 1200; Start-Process '%LIBRARY_URL%'"
"%VENV_PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port %LIBRARY_PORT% --reload --reload-dir app
if errorlevel 1 goto server_failed
goto end

:check_ok
echo [OK] Environment, dependencies, and port are ready.
goto end

:port_in_use
echo [Cannot start] Local port %LIBRARY_PORT% is already in use.
echo Close the program using that port and run this file again.
goto failed

:no_python
echo [Python missing] Python 3 was not found.
echo Install Python 3.11 or newer and enable Add Python to PATH.
goto failed

:setup_failed
echo [Setup failed] Could not create the environment or install packages.
echo Review the error shown above, then run this file again.
goto failed

:server_failed
echo [Server stopped] The server exited with an error.
goto failed

:failed
echo.
pause
exit /b 1

:end
endlocal
exit /b 0
