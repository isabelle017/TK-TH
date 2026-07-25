@echo off
chcp 65001 >nul
set BATFILE=C:\Users\isabe\tk-automation\run_sea.bat
echo === TikTok Auto Task Installer ===
echo.
schtasks /Create /TN "TikTokAuto\SEA 08:00" /TR "cmd.exe /c %BATFILE%" /SC DAILY /ST 08:00 /F /RL LIMITED
if %errorlevel% equ 0 (echo [OK] SEA 08:00) else (echo [FAIL] SEA 08:00)
schtasks /Create /TN "TikTokAuto\SEA 12:00" /TR "cmd.exe /c %BATFILE%" /SC DAILY /ST 12:00 /F /RL LIMITED
if %errorlevel% equ 0 (echo [OK] SEA 12:00) else (echo [FAIL] SEA 12:00)
schtasks /Create /TN "TikTokAuto\SEA 20:00" /TR "cmd.exe /c %BATFILE%" /SC DAILY /ST 20:00 /F /RL LIMITED
if %errorlevel% equ 0 (echo [OK] SEA 20:00) else (echo [FAIL] SEA 20:00)
echo.
echo Done.
pause
