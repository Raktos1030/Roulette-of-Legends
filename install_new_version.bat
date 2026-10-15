@echo off
rem Installs the new build (_new_version folder), then restarts the app.
rem The previous build is kept in backups\previous_exe. The Windows startup entry follows on its own.
rem Nothing is ever written inside the old build: if it can't be moved, the script waits.
cd /d "%~dp0"
if not exist "_new_version\Roulette of Legends\Roulette of Legends.exe" (
  echo Aucune nouvelle version a installer.
  pause
  exit /b
)
:wait
set RUNNING=
tasklist /FI "IMAGENAME eq Roulette LoL.exe" 2>nul | "%SystemRoot%\System32\find.exe" /I "Roulette LoL.exe" >nul && set RUNNING=1
tasklist /FI "IMAGENAME eq Roulette of Legends.exe" 2>nul | "%SystemRoot%\System32\find.exe" /I "Roulette of Legends.exe" >nul && set RUNNING=1
if defined RUNNING (
  echo L'application tourne encore : clic droit sur son icone pres de l'horloge, puis Quitter.
  echo Appuie ensuite sur une touche pour continuer.
  pause >nul
  goto wait
)
rem backups folder of older versions (French name)
if exist "sauvegardes" if not exist "backups" move "sauvegardes" "backups" >nul 2>nul
if not exist "backups" mkdir "backups"
set TRIES=0
set TARGET=
:move_old
if not exist "Roulette of Legends" goto install
if exist "backups\previous_exe" rmdir /s /q "backups\previous_exe" 2>nul
set TARGET=backups\previous_exe
if exist "%TARGET%" set TARGET=backups\previous_exe_%RANDOM%
move "Roulette of Legends" "%TARGET%" >nul 2>nul
if not exist "Roulette of Legends" goto install
rem a file of the old build is still open (the app just closed): retry
set /a TRIES+=1
if %TRIES% LSS 15 (
  echo Ancienne version encore utilisee, nouvel essai dans 2 secondes...
  "%SystemRoot%\System32\ping.exe" -n 3 127.0.0.1 >nul
  goto move_old
)
echo L'ancienne version est encore utilisee par un programme : une fenetre de l'Explorateur ouverte dedans,
echo un antivirus... Ferme-la, puis appuie sur une touche pour reessayer. Rien n'a ete supprime.
pause >nul
set TRIES=0
goto move_old
:install
move "_new_version\Roulette of Legends" "Roulette of Legends" >nul 2>nul
if not exist "Roulette of Legends\Roulette of Legends.exe" (
  echo L'installation n'a pas pu se faire : l'ancienne version est remise en place.
  if not exist "Roulette of Legends" if exist "%TARGET%" move "%TARGET%" "Roulette of Legends" >nul
  pause
  exit /b
)
rmdir "_new_version" 2>nul
echo Roulette of Legends installee.
start "" "Roulette of Legends\Roulette of Legends.exe"
"%SystemRoot%\System32\ping.exe" -n 3 127.0.0.1 >nul
