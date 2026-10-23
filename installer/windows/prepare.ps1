# Run by Sottovoce-Setup.exe after it copies the program: Python and the
# packages, with the PyTorch that sees this computer's GPU. The same steps as
# installer/install.ps1, on files the setup already put in place.
#
# It says where it is in -Status, one word per step, for the setup's
# progress page to show in the user's language:
#     python | torch:<build> | rest | done | error:<message>
# The log of every step is in <program>\setup.log.
param(
    [Parameter(Mandatory)] [string]$Program,
    [Parameter(Mandatory)] [string]$Data,
    [Parameter(Mandatory)] [string]$Status
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$App = Join-Path $Program "app"
$Py = Join-Path $App ".venv\Scripts\python.exe"
$Uv = Join-Path $Program "bin\uv.exe"
$Log = Join-Path $Program "setup.log"

function Say($word) { Set-Content -Path $Status -Value $word -Encoding Ascii }
function Run([string[]]$what) {
    # Into the log as plain text, and judged by the exit code alone. uv says
    # ordinary things on stderr ("Using CPython 3.12"), and Windows
    # PowerShell turns every such line, redirected, into an error: with
    # "Stop" the first one ended the setup.
    $ErrorActionPreference = "Continue"
    & $what[0] @($what[1..($what.Count - 1)]) 2>&1 | ForEach-Object { "$_" } | Add-Content -Path $Log -Encoding UTF8
    if ($LASTEXITCODE -ne 0) { throw "$(Split-Path $what[0] -Leaf) failed (exit code $LASTEXITCODE): see $Log" }
}

try {
    Set-Content -Path $Log -Value "Sottovoce setup, $(Get-Date -Format s)" -Encoding UTF8
    # uv keeps its Python and its cache in the program folder, and reads no
    # configuration of the user's: the install is the same on every machine.
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $Program "python"
    $env:UV_CACHE_DIR = Join-Path $Program "cache"
    $env:UV_PYTHON_PREFERENCE = "only-managed"
    $env:UV_NO_CONFIG = "1"

    if (-not (Test-Path $Py)) {
        Say "python"
        Run @($Uv, "venv", "--python", "3.12", (Join-Path $App ".venv"))
    }
    $pick = (& $Py (Join-Path $App "installer\gpu.py") --json) | ConvertFrom-Json
    Add-Content $Log "PyTorch: $($pick.why)"
    # PyTorch first, from its own index: see the comment in requirements.txt.
    Say "torch:$($pick.build)"
    Run @($Uv, "pip", "install", "--python", $Py, "--reinstall-package", "torch", "torch", "--index-url", $pick.index)
    Say "rest"
    Run @($Uv, "pip", "install", "--python", $Py, "-r", (Join-Path $App "requirements.txt"))

    New-Item -ItemType Directory -Force -Path (Join-Path $Data "transcripts") | Out-Null
    $glossary = Join-Path $Data "glossary.txt"
    if (-not (Test-Path $glossary)) { Copy-Item (Join-Path $App "glossary.example.txt") $glossary }
    # Where the calls are, for the uninstall to ask about the right folder.
    Set-Content (Join-Path $Program "data-folder.txt") -Value $Data -Encoding UTF8
    Add-Content $Log (& $Py -c "import torch; print('PyTorch', torch.__version__, 'GPU' if torch.cuda.is_available() else 'CPU')")
    Say "done"
} catch {
    Add-Content $Log "ERROR: $($_.Exception.Message)"
    # ASCII only: the setup reads this file byte by byte.
    Say ("error:" + ($_.Exception.Message -replace '[^\x20-\x7E]', '?'))
}
