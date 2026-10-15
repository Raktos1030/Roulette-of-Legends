@echo off
rem Serves the website locally on http://localhost:8000 and opens it in the browser. Ctrl+C to stop.
cd /d "%~dp0"
start "" http://localhost:8000/
python -m http.server 8000 --bind 127.0.0.1
