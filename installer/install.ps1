# Installs Sottovoce on Windows, or updates it: the same command does both.
#
#     irm https://raw.githubusercontent.com/thetouchsite/sottovoce/main/installer/install.ps1 | iex
#
# No administrator rights, no Python needed first, nothing paid for. uv
# (Astral, MIT or Apache-2.0), at a fixed version checked against its
# SHA-256, brings its own Python and installs the rest. Everything goes in
# one folder of the user's; the calls go in another, which an update or an
# uninstall never touches:
#
#     %LOCALAPPDATA%\Programs\Sottovoce   the program: uv, Python, the code, its .venv
#     %USERPROFILE%\Sottovoce             your calls and the name glossary
#
# Not Documents: on many computers OneDrive keeps a copy of Documents in the
# cloud, and the calls must not leave the machine.
#
# For tests, these change what it does:
#     SOTTOVOCE_DIR      the program folder
#     SOTTOVOCE_HOME     the folder of the calls
#     SOTTOVOCE_SOURCE   a folder with the code, instead of downloading the latest release
#     SOTTOVOCE_VERSION  a release to install, e.g. v1.5.0, instead of the latest
#     SOTTOVOCE_TORCH    cpu, cu126 or cu130, instead of asking installer\gpu.py

function Install-Sottovoce {
    # Everything inside a function: run through iex, an `exit` would close
    # the user's window, and variables would stay behind in it.
    $ErrorActionPreference = "Stop"
    $ProgressPreference = "SilentlyContinue"      # Windows PowerShell downloads ten times slower with the bar
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    $UvVersion = "0.13.0"
    $UvSha = @{
        "x86_64"  = "088962f9e7b7bd9ea740c04c650b2a21c8928c345bd99ac24350dc924dba656c"
        "aarch64" = "cb54028b59aa87f11cf6dec293ce000420043a49a8aea522e822a671321f8932"
    }
    $Repo = "thetouchsite/sottovoce"

    $Program = if ($env:SOTTOVOCE_DIR) { $env:SOTTOVOCE_DIR } else { Join-Path $env:LOCALAPPDATA "Programs\Sottovoce" }
    $DefaultData = -not $env:SOTTOVOCE_HOME
    $Data = if ($DefaultData) { Join-Path $env:USERPROFILE "Sottovoce" } else { $env:SOTTOVOCE_HOME }
    $App = Join-Path $Program "app"
    $Py = Join-Path $App ".venv\Scripts\python.exe"

    function Say($text) { Write-Host "  $text" }
    function Run($what) {
        # Native programs don't stop the script when they fail: check each one.
        & $what[0] @($what[1..($what.Count - 1)])
        if ($LASTEXITCODE -ne 0) { throw "$(Split-Path $what[0] -Leaf) failed (exit code $LASTEXITCODE)" }
    }

    Write-Host ""
    Say "Sottovoce: installing in $Program"
    Write-Host ""

    # A running copy keeps its files open, and they can't be replaced.
    $running = $true
    try { Invoke-WebRequest "http://127.0.0.1:8200/health" -UseBasicParsing -TimeoutSec 2 | Out-Null } catch { $running = $false }
    if ($running) { throw "Sottovoce is running: stop it (the power button on the page), then run this again." }

    New-Item -ItemType Directory -Force -Path (Join-Path $Program "bin") | Out-Null

    # --- uv, at a fixed version -------------------------------------------------
    $Uv = Join-Path $Program "bin\uv.exe"
    $have = if (Test-Path $Uv) { (& $Uv --version) -join "" } else { "" }
    if ($have -notmatch [regex]::Escape($UvVersion)) {
        $arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "aarch64" } else { "x86_64" }
        $name = "uv-$arch-pc-windows-msvc.zip"
        Say "Downloading uv $UvVersion..."
        $zip = Join-Path $env:TEMP $name
        Invoke-WebRequest "https://github.com/astral-sh/uv/releases/download/$UvVersion/$name" -OutFile $zip -UseBasicParsing
        $sha = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
        if ($sha -ne $UvSha[$arch]) { throw "uv download does not match its checksum: not installed." }
        $unpacked = Join-Path $env:TEMP "sottovoce-uv"
        Remove-Item $unpacked -Recurse -Force -ErrorAction SilentlyContinue
        Expand-Archive $zip -DestinationPath $unpacked -Force
        Copy-Item (Get-ChildItem $unpacked -Recurse -Filter "uv.exe" | Select-Object -First 1).FullName $Uv -Force
        Remove-Item $zip, $unpacked -Recurse -Force -ErrorAction SilentlyContinue
    }

    # uv keeps its Python and its cache in the program folder, and reads no
    # configuration of the user's: the install is the same on every machine.
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $Program "python"
    $env:UV_CACHE_DIR = Join-Path $Program "cache"
    $env:UV_PYTHON_PREFERENCE = "only-managed"
    $env:UV_NO_CONFIG = "1"

    # --- the code ---------------------------------------------------------------
    $new = Join-Path $Program "app.new"
    Remove-Item $new -Recurse -Force -ErrorAction SilentlyContinue
    if ($env:SOTTOVOCE_SOURCE) {
        Say "Copying the code from $($env:SOTTOVOCE_SOURCE)..."
        # Folders of the source's own, by full path: a bare "transcripts"
        # would also skip examples\transcripts.
        $src = (Resolve-Path $env:SOTTOVOCE_SOURCE).Path
        $skip = "transcripts", "models", "site", "research\fleurs", "research\ami", "research\results" |
            ForEach-Object { Join-Path $src $_ }
        robocopy $src $new /E /NFL /NDL /NJH /NJS /NP /XD .git .venv __pycache__ @skip `
            /XF (Join-Path $src ".lan-pin") (Join-Path $src "glossary.txt") | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "copying the code failed (robocopy $LASTEXITCODE)" }
    } else {
        $tag = $env:SOTTOVOCE_VERSION
        if (-not $tag) {
            $tag = (Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" -UseBasicParsing).tag_name
        }
        Say "Downloading Sottovoce $tag..."
        $zip = Join-Path $env:TEMP "sottovoce-$tag.zip"
        Invoke-WebRequest "https://github.com/$Repo/archive/refs/tags/$tag.zip" -OutFile $zip -UseBasicParsing
        $unpacked = Join-Path $env:TEMP "sottovoce-src"
        Remove-Item $unpacked -Recurse -Force -ErrorAction SilentlyContinue
        Expand-Archive $zip -DestinationPath $unpacked -Force
        Move-Item (Get-ChildItem $unpacked -Directory | Select-Object -First 1).FullName $new
        Remove-Item $zip, $unpacked -Recurse -Force -ErrorAction SilentlyContinue
    }

    # An update keeps what the code folder holds of yours: the environment
    # (so only what changed is downloaded), the voice models and the PIN
    # your phone already knows.
    # The old code goes and the new one takes its place around them: moving
    # .venv instead would cross Windows' 260-character limit on paths.
    New-Item -ItemType Directory -Force -Path $App | Out-Null
    $keep = ".venv", "models", ".lan-pin"
    Get-ChildItem $App -Force | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Recurse -Force
    Get-ChildItem $new -Force | Move-Item -Destination $App
    Remove-Item $new -Recurse -Force

    # --- Python and the packages -------------------------------------------------
    if (-not (Test-Path $Py)) {
        Say "Installing Python..."
        Run @($Uv, "venv", "--quiet", "--python", "3.12", (Join-Path $App ".venv"))
    }
    $torch = $env:SOTTOVOCE_TORCH
    if ($torch) {
        $index = "https://download.pytorch.org/whl/$torch"
        Say "PyTorch: $torch, as asked"
    } else {
        $pick = (& $Py (Join-Path $App "installer\gpu.py") --json) | ConvertFrom-Json
        $index = $pick.index
        Say "PyTorch: $($pick.why)"
    }
    # PyTorch first, from its own index: see the comment in requirements.txt.
    # Reinstalled every time, from the cache when it's already there, so a
    # new graphics card or driver gets the right build.
    Say "Installing PyTorch (about 2 GB the first time)..."
    Run @($Uv, "pip", "install", "--quiet", "--python", $Py, "--reinstall-package", "torch", "torch", "--index-url", $index)
    Say "Installing the rest..."
    Run @($Uv, "pip", "install", "--quiet", "--python", $Py, "-r", (Join-Path $App "requirements.txt"))

    # --- your folder, the launcher, the shortcuts ---------------------------------
    New-Item -ItemType Directory -Force -Path (Join-Path $Data "transcripts") | Out-Null
    $glossary = Join-Path $Data "glossary.txt"
    if (-not (Test-Path $glossary)) { Copy-Item (Join-Path $App "glossary.example.txt") $glossary }

    # %USERPROFILE% rather than the path itself: cmd reads a .cmd in the
    # console's code page, and a user name with an accent would break.
    $where = if ($DefaultData) { "%USERPROFILE%\Sottovoce" } else { $Data }
    $launcher = Join-Path $Program "Sottovoce.cmd"
    Set-Content $launcher -Encoding Ascii -Value @(
        "@echo off",
        "call `"%~dp0app\Start.bat`" --data `"$where\transcripts`" --glossary `"$where\glossary.txt`" %*"
    )

    $shell = New-Object -ComObject WScript.Shell
    foreach ($folder in [Environment]::GetFolderPath("Programs"), [Environment]::GetFolderPath("Desktop")) {
        $link = $shell.CreateShortcut((Join-Path $folder "Sottovoce.lnk"))
        $link.TargetPath = $launcher
        $link.WorkingDirectory = $App
        $link.Description = "Transcribe calls on this computer"
        $link.Save()
    }

    # Settings > Apps lists it, and removes it, like any other program.
    $version = (Select-String -Path (Join-Path $App "server.py") -Pattern '^VERSION = "(.+)"').Matches[0].Groups[1].Value
    $uninstall = Join-Path $Program "uninstall.ps1"
    Copy-Item (Join-Path $App "installer\uninstall.ps1") $uninstall -Force
    $key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Sottovoce"
    New-Item $key -Force | Out-Null
    # Without uv's cache: its files are the same ones as in .venv, linked,
    # and counting both would say twice what the disk holds.
    $size = [int]((Get-ChildItem $Program -Recurse -File -Force -ErrorAction SilentlyContinue |
        Where-Object { -not $_.FullName.StartsWith((Join-Path $Program "cache")) } |
        Measure-Object Length -Sum).Sum / 1KB)
    $values = @{
        DisplayName = "Sottovoce"; DisplayVersion = $version; Publisher = "TouchSite Software"
        InstallLocation = $Program; URLInfoAbout = "https://github.com/$Repo"
        UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$uninstall`""
    }
    foreach ($k in $values.Keys) { New-ItemProperty $key -Name $k -Value $values[$k] -PropertyType String -Force | Out-Null }
    foreach ($k in "NoModify", "NoRepair") { New-ItemProperty $key -Name $k -Value 1 -PropertyType DWord -Force | Out-Null }
    New-ItemProperty $key -Name EstimatedSize -Value $size -PropertyType DWord -Force | Out-Null

    Write-Host ""
    & $Py -c "import torch; ok = torch.cuda.is_available(); print('  PyTorch', torch.__version__, '|', ('GPU: ' + torch.cuda.get_device_name(0)) if ok else 'no GPU in use: it will run on the CPU, about ten times slower')"
    Write-Host ""
    Say "Sottovoce $version is installed."
    Say "Open it from the Start menu or the desktop. Your calls are kept in $Data"
    Say "To update it, run the same command again."
    Write-Host ""
}

try {
    Install-Sottovoce
} catch {
    Write-Host ""
    Write-Host "  Not installed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  Your calls were not touched. Run the command again; if it fails the same way, see"
    Write-Host "  https://thetouchsite.github.io/sottovoce/troubleshooting/"
    Write-Host ""
    if ($env:SOTTOVOCE_SOURCE) { throw }     # tests must fail, not just print
}
