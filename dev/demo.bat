@echo off
rem Demo of the app with a made-up player (dev\demo.py): your own data, LoL and the Windows startup entry are left alone.
cd /d "%~dp0.."
python dev\demo.py %*
if errorlevel 1 pause
