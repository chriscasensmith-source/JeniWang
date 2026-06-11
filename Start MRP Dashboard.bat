@echo off
setlocal
rem ============================================================
rem  MRP Ordering Assistant - double-click to start
rem  First run: installs the tool (needs Python from python.org).
rem  Every other run: starts the dashboard and opens the browser.
rem  Ingest the weekly file by dragging it onto the web page.
rem  Leave this window open while you work; close it when done.
rem ============================================================
cd /d "%~dp0"

rem Machines often have more than one Python that don't share libraries.
rem Prefer whichever one already has the dependencies installed; only if
rem none does, pick the first working Python and install into it.
rem (The fake Microsoft Store stub fails these probes, so it gets skipped.)
set "DEPS=import yaml, fastapi, uvicorn, openpyxl, pandas, multipart"
set "PY="
py -3 -c "%DEPS%" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "%DEPS%" >nul 2>nul && set "PY=python"
if defined PY goto run

py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY (
    echo.
    echo  Python was not found on this computer.
    echo.
    echo  1. Go to  https://www.python.org/downloads/  and download Python.
    echo  2. Run the installer and CHECK the box "Add python.exe to PATH".
    echo  3. Double-click this file again.
    echo.
    pause
    exit /b 1
)

echo First-time setup: installing the MRP Ordering Assistant...
echo This happens only once and takes a minute or two.
%PY% -m pip install -e . || (
    echo.
    echo  Install failed - see the messages above.
    echo  Take a screenshot of this window if you need help.
    echo.
    pause
    exit /b 1
)
%PY% -c "%DEPS%" || (
    echo.
    echo  Something is still missing after the install - see above.
    echo.
    pause
    exit /b 1
)

:run

echo Starting the dashboard... your browser will open in a moment.
echo Leave this window open while you work. Close it when you're done.
start /b "" cmd /c "timeout /t 2 >nul & start http://127.0.0.1:8000"
%PY% -m mrp_assistant serve
echo.
echo The dashboard has stopped. If that was unexpected, read the messages
echo above (a common cause: it was already running in another window).
pause
