@echo off
rem Unattended update: pull fresh carrier data, rebuild dashboard.html, push to GitHub Pages,
rem then mail the result to sales@heungaline.co.th. Run by the scheduled task "HCM Schedule Update"
rem (Mon-Fri 09:00). Log: update_log.txt
cd /d "%~dp0"
echo ===== %date% %time% ===== >> update_log.txt
set RESULT=ok
"%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" build_hcm_schedule.py < nul >> update_log.txt 2>&1
if errorlevel 1 (
  echo BUILD FAILED - nothing pushed >> update_log.txt
  set RESULT=failed
  goto mail
)
git add dashboard.html >> update_log.txt 2>&1
git diff --cached --quiet
if %errorlevel% equ 0 (
  echo No changes - nothing to push >> update_log.txt
  set RESULT=nochange
  goto mail
)
git commit -q -m "Auto-update HCM schedule %date%" >> update_log.txt 2>&1
git push >> update_log.txt 2>&1
if errorlevel 1 (
  echo PUSH FAILED >> update_log.txt
  set RESULT=failed
  goto mail
)
echo Pushed OK >> update_log.txt
:mail
set DRAFT=
if "%HCM_MAIL_DRAFT%"=="1" set DRAFT=-DraftOnly
"%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" svms_space.py < nul >> update_log.txt 2>&1
"%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" build_hcm_schedule.py --mail-body %RESULT% < nul >> update_log.txt 2>&1
if errorlevel 1 (
  echo MAIL BODY FAILED >> update_log.txt
  goto done
)
powershell -NoProfile -File "%~dp0send_update_mail.ps1" %DRAFT% < nul >> update_log.txt 2>&1
if errorlevel 1 echo MAIL FAILED >> update_log.txt
:done
if "%RESULT%"=="failed" exit /b 1
exit /b 0
