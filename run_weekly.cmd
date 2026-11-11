@echo off
rem ---------------------------------------------------------------------------
rem  TI Agent - weekly run (AI suggestions for this week's S&P 500 picks)
rem
rem  Double-click this file, or run it from a terminal:
rem      run_weekly.cmd                        all of this week's picks (~20 min)
rem      run_weekly.cmd --tickers AAPL MSFT    only these tickers
rem      run_weekly.cmd --no-telegram          skip the Telegram digest
rem
rem  Output goes to the screen and to logs\weekly_run.log.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [x] No .venv found. Run scripts\setup.ps1 first.
    set "RC=2"
    goto :finish
)

rem --- Ollama must be running; start it if it isn't ---------------------------
curl.exe -s -o nul --max-time 3 http://127.0.0.1:11434/api/version
if errorlevel 1 (
    echo [..] Ollama isn't running - starting it...
    start "Ollama" /min ollama serve
    timeout /t 8 /nobreak >nul
    curl.exe -s -o nul --max-time 3 http://127.0.0.1:11434/api/version
    if errorlevel 1 (
        echo [x] Could not reach Ollama at 127.0.0.1:11434. Open the Ollama app and try again.
        set "RC=2"
        goto :finish
    )
)

echo.
echo   TI Agent weekly run - AI suggestions for this week's S^&P 500 picks (about 20 min)
echo   Tip: close your browser first; the model needs about 5 GB of free memory.
echo.

set "TI_LOG_FILE=%~dp0logs\weekly_run.log"
"%PY%" -m orchestration.weekly_run %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo [ok] Done: every pick got both suggestions. Open the app to see them.
) else if "%RC%"=="1" (
    echo [!] Partly done: some tickers failed. Details in logs\weekly_run.log
) else (
    echo [x] The run failed. Details in logs\weekly_run.log
)

:finish
rem Keep the window open when double-clicked (not when run from a terminal or with TI_NO_PAUSE=1).
if not defined TI_NO_PAUSE (
    echo %cmdcmdline% | find /i "%~nx0" >nul && pause
)
exit /b %RC%
