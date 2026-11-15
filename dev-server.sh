#!/bin/bash
# GitHup - Local dev server
# Usage: ./dev-server.sh [--no-dev-mode] [--lan] [port]
#   port            default: 8000
#   --no-dev-mode   render the page exactly as production would (no DEV MODE banner)
#   --lan           listen on all interfaces so phones/tablets on your network can
#                   connect (prints the addresses to open); default is 127.0.0.1 only
#
# Generates 90 days of example data for examples/.githup.yml, builds the
# status page from it into .dev/site and serves it with python -m http.server.
# DEV_MODE is on by default so the page shows the dev-only banner.
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=8000
HOST=127.0.0.1
export DEV_MODE=1

for arg in "$@"; do
    case "$arg" in
        --no-dev-mode) export DEV_MODE=0 ;;
        --lan) HOST=0.0.0.0 ;;
        ''|*[!0-9]*) echo "Usage: $0 [--no-dev-mode] [--lan] [port]" >&2; exit 1 ;;
        *) PORT="$arg" ;;
    esac
done

lan_urls() {
    # This machine's IPv4 addresses (Windows, macOS or Linux), minus loopback
    case "$OSTYPE" in
        msys*|cygwin*|win32*) ADDRS="$(ipconfig | awk -F': *' '/IPv4/{print $2}' | tr -d '\r')" ;;
        darwin*) ADDRS="$(ifconfig | awk '/inet /{print $2}')" ;;
        *) ADDRS="$(hostname -I 2>/dev/null)" ;;
    esac
    echo "On your local network (--lan), open one of these on the other device:"
    for a in $ADDRS; do
        case "$a" in 127.*|'') ;; *) echo "    http://$a:$PORT$1" ;; esac
    done
    echo "  (usually the 192.168.x.x one; allow Python through the firewall if asked)"
}

PY="$(command -v python3 || command -v python)"
cd "$DIR"
"$PY" -m githup demo --config examples/.githup.yml --data-dir .dev/data
"$PY" -m githup site --config examples/.githup.yml --data-dir .dev/data \
    --incidents-file .dev/data/incidents.json --out .dev/site --no-deploy

echo "GitHup example status page (DEV_MODE=$DEV_MODE) at http://127.0.0.1:$PORT"
if [ "$HOST" = "0.0.0.0" ]; then lan_urls ""; fi
"$PY" -m http.server "$PORT" --bind "$HOST" --directory .dev/site
