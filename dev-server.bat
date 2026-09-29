@echo off
setlocal
REM GitHup - Local dev server (Windows)
REM Usage: dev-server.bat [--no-dev-mode] [port]
REM   port            default: 8000
REM   --no-dev-mode   render the page exactly as production would (no DEV MODE banner)
REM
REM Generates 90 days of example data for examples\.githup.yml, builds the
REM status page from it into .dev\site and serves it with python -m http.server.
REM DEV_MODE is on by default so the page shows the dev-only banner.

set "DIR=%~dp0"
set "PORT=8000"
set "DEV_MODE=1"

:args
if "%~1"=="" goto run
if /i "%~1"=="--no-dev-mode" (
    set "DEV_MODE=0"
) else (
    set "PORT=%~1"
)
shift
goto args

:run
cd /d "%DIR%"
python -m githup demo --config examples/.githup.yml --data-dir .dev/data || exit /b 1
python -m githup site --config examples/.githup.yml --data-dir .dev/data --incidents-file .dev/data/incidents.json --out .dev/site --no-deploy || exit /b 1

echo GitHup example status page (DEV_MODE=%DEV_MODE%) at http://127.0.0.1:%PORT%
python -m http.server %PORT% --bind 127.0.0.1 --directory .dev/site
