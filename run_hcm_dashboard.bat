@echo off
rem Double-click to open the Bangkok / Laem Chabang -> Ho Chi Minh City schedule dashboard.
rem The page opens in your browser; its Refresh button pulls fresh data from the carriers.
rem Close this window to stop the helper.
cd /d "%~dp0"
echo Starting dashboard helper... (close this window to stop)
python build_hcm_schedule.py --serve
if %errorlevel% equ 9009 py build_hcm_schedule.py --serve
if errorlevel 1 pause
