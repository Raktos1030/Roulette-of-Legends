@echo off
rem Builds both Windows apps for a release into _release\, each as a standalone folder (exe + its own data, without
rem personal files) and a .zip to publish. The macOS Lite is built by the release workflow on GitHub.
cd /d "%~dp0"
python packaging\build.py full || goto failed
python packaging\build.py lite || goto failed
echo.
echo Termine : dossier _release (Roulette-of-Legends-windows.zip et Roulette-of-Legends-Lite-windows.zip).
pause
exit /b
:failed
echo La compilation a echoue.
pause
