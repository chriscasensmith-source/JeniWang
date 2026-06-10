#!/bin/bash
# MRP Ordering Assistant — double-click (or run) to start.
# First run installs the tool; every run starts the dashboard and
# opens the browser. Ingest weekly files by dragging them onto the page.
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null; then
    echo "Python 3 was not found. Install it from https://www.python.org/downloads/"
    read -r -p "Press Enter to close."
    exit 1
fi

if ! python3 -c "import mrp_assistant" >/dev/null 2>&1; then
    echo "First-time setup: installing the MRP Ordering Assistant..."
    python3 -m pip install -e . || { read -r -p "Install failed. Press Enter to close."; exit 1; }
fi

echo "Starting the dashboard... your browser will open in a moment."
echo "Leave this window open while you work."
( sleep 2; open "http://127.0.0.1:8000" 2>/dev/null || xdg-open "http://127.0.0.1:8000" ) &
python3 -m mrp_assistant serve
