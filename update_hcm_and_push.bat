@echo off
rem Unattended update: pull fresh carrier data, rebuild dashboard.html, push to GitHub Pages.
rem Run by the Windows scheduled task "HCM Schedule Update" (Mon-Fri 08:30). Log: update_log.txt
cd /d "%~dp0"
echo ===== %date% %time% ===== >> update_log.txt
"%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" build_hcm_schedule.py < nul >> update_log.txt 2>&1
if not exist "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" py build_hcm_schedule.py < nul >> update_log.txt 2>&1
if errorlevel 1 (
  echo BUILD FAILED - nothing pushed >> update_log.txt
  exit /b 1
)
git add dashboard.html >> update_log.txt 2>&1
git diff --cached --quiet
if %errorlevel% equ 0 (
  echo No changes - nothing to push >> update_log.txt
  exit /b 0
)
git commit -q -m "Auto-update HCM schedule %date%" >> update_log.txt 2>&1
git push >> update_log.txt 2>&1
if errorlevel 1 (echo PUSH FAILED >> update_log.txt & exit /b 1)
echo Pushed OK >> update_log.txt
