@echo off
rem ============================================================
rem  MRP Ordering Assistant - double-click to start
rem  First run: installs the tool (needs Python from python.org,
rem  installed with the "Add python.exe to PATH" box checked).
rem  Every other run: starts the dashboard and opens the browser.
rem  Ingest the weekly file by dragging it onto the web page.
rem ============================================================
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found.
    echo Install it from https://www.python.org/downloads/
    echo and CHECK the "Add python.exe to PATH" box in the installer.
    pause
    exit /b 1
)

python -c "import mrp_assistant" >nul 2>nul
if errorlevel 1 (
    echo First-time setup: installing the MRP Ordering Assistant...
    python -m pip install -e . || (
        echo.
        echo Install failed - see the messages above.
        pause
        exit /b 1
    )
)

echo Starting the dashboard... your browser will open in a moment.
echo Leave this window open while you work. Close it when you're done.
start /b "" cmd /c "timeout /t 2 >nul & start http://127.0.0.1:8000"
python -m mrp_assistant serve
