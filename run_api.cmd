@echo off
rem ---------------------------------------------------------------------------
rem  TI Agent - app API for the Flutter app on GitHub Pages
rem
rem  Serves the Django site (production settings) on 127.0.0.1:8001 with waitress.
rem  Expose ONLY /api/ to the internet through a Cloudflare Tunnel (see README, "App").
rem  Needs DJANGO_SECRET_KEY and DJANGO_ALLOWED_HOSTS (your tunnel hostname) in .env.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" ( echo [x] No .venv found. Run scripts\setup.ps1 first. & exit /b 2 )
call scripts\ensure_db.cmd || exit /b 2

set "DJANGO_DEBUG=false"
set "DJANGO_BEHIND_PROXY=true"
echo   App API on http://127.0.0.1:8001/api/  (Ctrl+C to stop)
cd /d "%~dp0web"
rem cloudflared connects from 127.0.0.1 and says the visitor used https (X-Forwarded-Proto).
"%PY%" -m waitress --listen=127.0.0.1:8001 --threads=4 --trusted-proxy=127.0.0.1 ^
    --trusted-proxy-headers=x-forwarded-proto tiweb.wsgi:application
