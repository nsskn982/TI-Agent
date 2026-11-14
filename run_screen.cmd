@echo off
rem ---------------------------------------------------------------------------
rem  TI Agent - weekly stock screen (S&P 500 + S&P MidCap 400, Friday night)
rem
rem      run_screen.cmd                    refresh, screen, backfill new picks, prune old data
rem      run_screen.cmd --skip-refresh     re-screen stored data without downloading
rem      run_screen.cmd --keep-old         skip the retention step
rem
rem  The first run downloads ~800 days for ~900 stocks (1.5-2 h); later runs only new days.
rem  Output: screen + logs\screen_run.log.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" ( echo [x] No .venv found. Run scripts\setup.ps1 first. & set "RC=2" & goto :finish )
call scripts\ensure_db.cmd || ( set "RC=2" & goto :finish )

set "TI_LOG_FILE=%~dp0logs\screen_run.log"
"%PY%" -m orchestration.screen_run %*
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" ( echo [ok] Screen done. ) else ( echo [x] Screen failed. Details in logs\screen_run.log )

:finish
if not defined TI_NO_PAUSE ( echo %cmdcmdline% | find /i "%~nx0" >nul && pause )
exit /b %RC%
