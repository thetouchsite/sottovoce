#!/usr/bin/env bash
# Installs Sottovoce on Linux or macOS, or updates it: the same command does both.
#
#     curl -fsSL https://raw.githubusercontent.com/thetouchsite/sottovoce/main/installer/install.sh | bash
#
# No root, no Python needed first, nothing paid for. uv (Astral, MIT or
# Apache-2.0), at a fixed version checked against its SHA-256, brings its own
# Python and installs the rest. The program goes in one folder, the calls in
# another, which an update or an uninstall never touches:
#
#     Linux   ~/.local/share/sottovoce              the program
#     macOS   ~/Library/Application Support/Sottovoce
#     both    ~/Sottovoce                           your calls and the name glossary
#
# For tests, these change what it does:
#     SOTTOVOCE_DIR      the program folder
#     SOTTOVOCE_HOME     the folder of the calls
#     SOTTOVOCE_SOURCE   a folder with the code, instead of downloading the latest release
#     SOTTOVOCE_VERSION  a release to install, e.g. v1.5.0, instead of the latest
#     SOTTOVOCE_TORCH    cpu, cu126, cu130 or pypi, instead of asking installer/gpu.py
#
# Everything is inside main(), called on the last line: piped into bash, a
# download cut halfway runs nothing instead of half a script.

main() {
    set -euo pipefail

    local uv_version=0.13.0 repo=thetouchsite/sottovoce
    local system arch target sha program data app py
    system=$(uname -s)
    arch=$(uname -m)
    case "$system-$arch" in
        Linux-x86_64)  target=x86_64-unknown-linux-gnu  sha=1468ebd5a5541121837c5a2817b9972ba6090fa6caa3d142620850a47fb75154 ;;
        Linux-aarch64) target=aarch64-unknown-linux-gnu sha=3ccfb6af6e242433eb552f7d9676abd5412c6595c497e990d9c8cb7b5bd4d2c3 ;;
        Darwin-arm64)  target=aarch64-apple-darwin      sha=a9c1b29002cf3c83f07fa9cd8a887a3be0107d90e23189721221e7257db8e3d6 ;;
        Darwin-x86_64)
            echo "  PyTorch no longer ships for Intel Macs: Sottovoce needs a Mac with Apple silicon." >&2
            exit 1 ;;
        *)
            echo "  $system on $arch is not supported by this installer." >&2
            exit 1 ;;
    esac

    if [ "$system" = Darwin ]; then
        program=${SOTTOVOCE_DIR:-"$HOME/Library/Application Support/Sottovoce"}
    else
        program=${SOTTOVOCE_DIR:-"${XDG_DATA_HOME:-$HOME/.local/share}/sottovoce"}
    fi
    data=${SOTTOVOCE_HOME:-"$HOME/Sottovoce"}
    app="$program/app"
    py="$app/.venv/bin/python"

    trap 'echo; echo "  Not installed: see the message above. Your calls were not touched."; echo "  Run the command again; if it fails the same way, see https://thetouchsite.github.io/sottovoce/troubleshooting/"' ERR

    echo
    echo "  Sottovoce: installing in $program"
    echo

    # A running copy keeps its files open, and they would change under it.
    if curl -fsS --max-time 2 http://127.0.0.1:8200/health >/dev/null 2>&1; then
        echo "  Sottovoce is running: stop it (the power button on the page), then run this again." >&2
        exit 1
    fi

    mkdir -p "$program/bin"
    local tmp
    tmp=$(mktemp -d)

    # --- uv, at a fixed version ----------------------------------------------
    local uv="$program/bin/uv"
    if ! "$uv" --version 2>/dev/null | grep -qF "$uv_version"; then
        echo "  Downloading uv $uv_version..."
        curl -fsSL "https://github.com/astral-sh/uv/releases/download/$uv_version/uv-$target.tar.gz" -o "$tmp/uv.tar.gz"
        local got
        if command -v sha256sum >/dev/null 2>&1; then
            got=$(sha256sum "$tmp/uv.tar.gz" | cut -d' ' -f1)
        else
            got=$(shasum -a 256 "$tmp/uv.tar.gz" | cut -d' ' -f1)
        fi
        if [ "$got" != "$sha" ]; then
            echo "  uv download does not match its checksum: not installed." >&2
            exit 1
        fi
        tar -xzf "$tmp/uv.tar.gz" -C "$tmp"
        cp "$tmp/uv-$target/uv" "$uv"
        chmod +x "$uv"
    fi

    # uv keeps its Python and its cache in the program folder, and reads no
    # configuration of the user's: the install is the same on every machine.
    export UV_PYTHON_INSTALL_DIR="$program/python" UV_CACHE_DIR="$program/cache"
    export UV_PYTHON_PREFERENCE=only-managed UV_NO_CONFIG=1

    # --- the code ------------------------------------------------------------
    local new="$program/app.new"
    rm -rf "$new"
    if [ -n "${SOTTOVOCE_SOURCE:-}" ]; then
        echo "  Copying the code from $SOTTOVOCE_SOURCE..."
        mkdir -p "$new"
        (cd "$SOTTOVOCE_SOURCE" && tar -cf - \
            --exclude=.git --exclude=.venv --exclude=./transcripts --exclude=./models \
            --exclude=__pycache__ --exclude=./site --exclude=./research/fleurs \
            --exclude=./research/ami --exclude=./research/results \
            --exclude=.lan-pin --exclude=./glossary.txt .) | tar -xf - -C "$new"
    else
        local tag=${SOTTOVOCE_VERSION:-}
        if [ -z "$tag" ]; then
            tag=$(curl -fsSL "https://api.github.com/repos/$repo/releases/latest" \
                  | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1)
        fi
        echo "  Downloading Sottovoce $tag..."
        curl -fsSL "https://github.com/$repo/archive/refs/tags/$tag.tar.gz" -o "$tmp/src.tar.gz"
        mkdir -p "$tmp/src"
        tar -xzf "$tmp/src.tar.gz" -C "$tmp/src"
        mv "$tmp/src/"*/ "$new"
    fi

    # An update keeps what the code folder holds of yours: the environment
    # (so only what changed is downloaded), the voice models and the PIN
    # your phone already knows.
    # The old code goes and the new one takes its place around them, as on
    # Windows, where moving .venv would cross the limit on path length.
    mkdir -p "$app"
    find "$app" -mindepth 1 -maxdepth 1 ! -name .venv ! -name models ! -name .lan-pin -exec rm -rf {} +
    (shopt -s dotglob && mv "$new"/* "$app"/)
    rmdir "$new"

    # --- Python and the packages -----------------------------------------------
    if [ ! -x "$py" ]; then
        echo "  Installing Python..."
        "$uv" venv --quiet --python 3.12 "$app/.venv"
    fi
    local build=${SOTTOVOCE_TORCH:-} why index
    if [ -n "$build" ]; then
        why="$build, as asked"
    else
        read -r build why < <("$py" "$app/installer/gpu.py")
    fi
    echo "  PyTorch: $why"
    # PyTorch first, from its own index: see the comment in requirements.txt.
    # Reinstalled every time, from the cache when it's already there, so a
    # new graphics card or driver gets the right build.
    echo "  Installing PyTorch..."
    if [ "$build" = pypi ]; then
        "$uv" pip install --quiet --python "$py" --reinstall-package torch torch
    else
        index="https://download.pytorch.org/whl/$build"
        "$uv" pip install --quiet --python "$py" --reinstall-package torch torch --index-url "$index"
    fi
    echo "  Installing the rest..."
    "$uv" pip install --quiet --python "$py" -r "$app/requirements.txt"

    # --- your folder, the launcher ---------------------------------------------
    mkdir -p "$data/transcripts"
    if [ ! -f "$data/glossary.txt" ]; then
        cp "$app/glossary.example.txt" "$data/glossary.txt"
    fi

    local launcher="$program/sottovoce"
    cat > "$launcher" <<EOF
#!/usr/bin/env bash
# Starts Sottovoce with your calls in $data. Written by the installer.
exec "$app/start.sh" --data "$data/transcripts" --glossary "$data/glossary.txt" "\$@"
EOF
    chmod +x "$launcher" "$app/start.sh"
    cp "$app/installer/uninstall.sh" "$program/uninstall.sh"
    chmod +x "$program/uninstall.sh"

    local where
    if [ "$system" = Darwin ]; then
        # A .command opens in Terminal with a double-click, from Finder or the Dock.
        mkdir -p "$HOME/Applications"
        where="$HOME/Applications/Sottovoce.command"
        printf '#!/usr/bin/env bash\nexec "%s" "$@"\n' "$launcher" > "$where"
        chmod +x "$where"
    else
        mkdir -p "$HOME/.local/share/applications"
        where="the applications menu"
        cat > "$HOME/.local/share/applications/sottovoce.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Sottovoce
Comment=Transcribe calls on this computer
Exec="$launcher"
Terminal=true
Categories=AudioVideo;Office;
EOF
    fi
    rm -rf "$tmp"

    local version
    version=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$app/server.py")
    echo
    "$py" -c "import torch; ok = torch.cuda.is_available(); print('  PyTorch', torch.__version__, '|', ('GPU: ' + torch.cuda.get_device_name(0)) if ok else 'no NVIDIA GPU in use: it will run on the CPU, about ten times slower')"
    echo
    echo "  Sottovoce $version is installed."
    echo "  Start it from $where, or with: \"$launcher\""
    echo "  Your calls are kept in $data"
    echo "  To update it, run the same command again."
    echo
}

main "$@"
