#!/bin/bash
# GitHup - Local dev server
# Usage: ./dev-server.sh [--no-dev-mode] [port]
#   port            default: 8000
#   --no-dev-mode   render the page exactly as production would (no DEV MODE banner)
#
# Generates 90 days of example data for examples/.githup.yml, builds the
# status page from it into .dev/site and serves it with python -m http.server.
# DEV_MODE is on by default so the page shows the dev-only banner.
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=8000
export DEV_MODE=1

for arg in "$@"; do
    case "$arg" in
        --no-dev-mode) export DEV_MODE=0 ;;
        ''|*[!0-9]*) echo "Usage: $0 [--no-dev-mode] [port]" >&2; exit 1 ;;
        *) PORT="$arg" ;;
    esac
done

PY="$(command -v python3 || command -v python)"
cd "$DIR"
"$PY" -m githup demo --config examples/.githup.yml --data-dir .dev/data
"$PY" -m githup site --config examples/.githup.yml --data-dir .dev/data \
    --incidents-file .dev/data/incidents.json --out .dev/site --no-deploy

echo "GitHup example status page (DEV_MODE=$DEV_MODE) at http://127.0.0.1:$PORT"
"$PY" -m http.server "$PORT" --bind 127.0.0.1 --directory .dev/site
