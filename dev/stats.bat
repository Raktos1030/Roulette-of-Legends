@echo off
rem Usage stats, live in the browser (dev\stats.py): the page follows the counts while this window stays open.
title Stats Roulette of Legends
cd /d "%~dp0.."
python dev\stats.py %*
if errorlevel 1 pause
