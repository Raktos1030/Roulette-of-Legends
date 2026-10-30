@echo off
rem Usage stats in one page (dev\stats.py): new players, players of the day and week, updates, downloads, site visits.
cd /d "%~dp0.."
python dev\stats.py %*
if errorlevel 1 pause
