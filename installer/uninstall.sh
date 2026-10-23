#!/usr/bin/env bash
# Removes Sottovoce installed by install.sh: the program folder and its
# launchers. Then it asks whether to delete what is yours too: the calls,
# and the models it downloaded. Yes to both leaves the computer as it was
# before Sottovoce; no is what an empty answer means.
#
#     --keep    no questions, keep the calls and the models (for scripts and tests)
set -euo pipefail
program=$(cd "$(dirname "$0")" && pwd)
keep=false
[ "${1:-}" = "--keep" ] && keep=true

if curl -fsS --max-time 2 http://127.0.0.1:8200/health >/dev/null 2>&1; then
    echo "  Sottovoce is running: stop it (the power button on the page), then run this again." >&2
    exit 1
fi

# Where the calls are: the installer wrote it down, as it may not be the default.
data="$HOME/Sottovoce"
if [ -f "$program/data-folder.txt" ]; then
    data=$(cat "$program/data-folder.txt")
fi
# Sottovoce's own models only, not the whole cache: other programs may use it.
hub="${HF_HOME:-$HOME/.cache/huggingface}/hub"
models=()
for m in models--openai--whisper-large-v3 models--Qwen--Qwen3-4B-Instruct-2507; do
    if [ -d "$hub/$m" ]; then
        models+=("$hub/$m")
    fi
done

drop_calls=false
drop_models=false
if [ "$keep" = false ] && [ -r /dev/tty ]; then
    if [ -d "$data" ]; then
        printf '  Delete your calls too, recordings and transcripts, in %s? They cannot be recovered. [y/N] ' "$data"
        read -r answer < /dev/tty
        case "$answer" in y|Y|yes|s|S|si) drop_calls=true ;; esac
    fi
    if [ "${#models[@]}" -gt 0 ]; then
        printf '  Delete the models Sottovoce downloaded too (%s)? [y/N] ' "$(du -sh "${models[@]}" 2>/dev/null | awk '{print $1}' | paste -sd+ -)"
        read -r answer < /dev/tty
        case "$answer" in y|Y|yes|s|S|si) drop_models=true ;; esac
    fi
fi

echo
echo "  Removing Sottovoce from $program"
rm -f "$HOME/.local/share/applications/sottovoce.desktop" "$HOME/Applications/Sottovoce.command"
cd /
rm -rf "$program"
if [ "$drop_calls" = true ]; then
    rm -rf "$data"
fi
if [ "$drop_models" = true ]; then
    rm -rf "${models[@]}"
fi
echo
echo "  Done."
if [ -d "$data" ]; then
    echo "  Your calls and glossary are still in $data"
fi
if [ "${#models[@]}" -gt 0 ] && [ "$drop_models" = false ]; then
    echo "  The models are still in $hub"
fi
echo
