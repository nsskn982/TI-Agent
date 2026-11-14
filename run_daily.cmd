@echo off
rem ---------------------------------------------------------------------------
rem  TI Agent - daily refresh (weekdays, after the US close)
rem
rem      run_daily.cmd                     new prices, news, filings, fundamentals, macro
rem      run_daily.cmd --days 730          first-time backfill
rem      run_daily.cmd --tickers AAPL      only these tickers
rem
rem  Only data newer than what is stored is downloaded (see ingestion/refresh.py), then the new
rem  text is chunked, embedded and scored. Output: screen + logs\daily_run.log.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" ( echo [x] No .venv found. Run scripts\setup.ps1 first. & set "RC=2" & goto :finish )
call scripts\ensure_db.cmd || ( set "RC=2" & goto :finish )

set "TI_LOG_FILE=%~dp0logs\daily_run.log"
rem One live view: ingest new data, then chunk, embed and score it (orchestration/daily_run.py).
"%PY%" -m orchestration.daily_run %*
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" ( echo [ok] Daily refresh done. ) else ( echo [!] Finished with errors. Details in logs\daily_run.log )

:finish
if not defined TI_NO_PAUSE ( echo %cmdcmdline% | find /i "%~nx0" >nul && pause )
exit /b %RC%
