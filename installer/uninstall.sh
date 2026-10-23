#!/usr/bin/env bash
# Removes Sottovoce installed by install.sh: the program folder and its
# launchers. Your calls stay where they are.
set -euo pipefail
program=$(cd "$(dirname "$0")" && pwd)

if curl -fsS --max-time 2 http://127.0.0.1:8200/health >/dev/null 2>&1; then
    echo "  Sottovoce is running: stop it (the power button on the page), then run this again." >&2
    exit 1
fi

echo
echo "  Removing Sottovoce from $program"
rm -f "$HOME/.local/share/applications/sottovoce.desktop" "$HOME/Applications/Sottovoce.command"
cd /
rm -rf "$program"
echo
echo "  Done. Your calls and glossary are still in ~/Sottovoce, unless you chose another folder."
echo "  The models (about 11 GB) are in ~/.cache/huggingface: delete it too if nothing else uses it."
echo
