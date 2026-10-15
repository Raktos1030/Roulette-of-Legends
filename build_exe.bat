@echo off
rem Builds "Roulette of Legends.exe" into _new_version\ after a change to the Python code (.py).
rem Not needed for ui\, guides or stats (data\): the app reads them on every launch.
rem Then run install_new_version.bat to swap it in.
cd /d "%~dp0"
python packaging\build.py full --dist "%~dp0_new_version" --dev
if errorlevel 1 (
  echo La compilation a echoue.
  pause
  exit /b
)
echo.
echo Termine : _new_version\Roulette of Legends. Lance install_new_version.bat pour l'installer.
pause
