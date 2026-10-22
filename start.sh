#!/usr/bin/env bash
# Starts Sottovoce and opens the page. The Linux and macOS twin of Start.bat.
# Extra arguments go to server.py, so this works too:
#   ./start.sh --no-model --data examples/transcripts --glossary examples/glossary.txt
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    echo
    echo "  Not installed yet: run ./install.sh first."
    echo
    exit 1
fi

# The page to open follows --port, if one was passed.
port=8200
prev=
for arg in "$@"; do
    case "$arg" in
        --port=*) port=${arg#--port=} ;;
    esac
    if [ "$prev" = "--port" ]; then
        port=$arg
    fi
    prev=$arg
done
url="http://127.0.0.1:$port"

if command -v xdg-open >/dev/null 2>&1; then
    opener=xdg-open
elif command -v open >/dev/null 2>&1; then
    opener=open
else
    opener=
fi

echo
echo "  Sottovoce - starting..."
echo

# Open the browser once the server answers, not before: loading the model
# takes about twenty seconds (longer the first time, when it's downloaded),
# and a page opened too early shows an error. $$ is the server itself after
# the exec below: if it stops, so does the wait.
if [ -n "$opener" ]; then
    (
        while kill -0 "$$" 2>/dev/null; do
            if .venv/bin/python -c "import urllib.request, sys; urllib.request.urlopen(sys.argv[1] + '/health', timeout=1)" "$url" 2>/dev/null; then
                "$opener" "$url" >/dev/null 2>&1 || true
                break
            fi
            sleep 1
        done
    ) &
else
    echo "  Open $url in your browser."
fi

exec .venv/bin/python server.py "$@"
