# Builds the Windows setup: dist\Sottovoce-Setup-<version>.exe
#
#     powershell -ExecutionPolicy Bypass -File installer\windows\build.ps1
#
# Needs Inno Setup 6 (winget install JRSoftware.InnoSetup). Downloads uv at
# the version the one-command install uses, checked against the same
# SHA-256; draws the pictures (art.py, with Pillow through uv); compiles.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$here = $PSScriptRoot
$root = (Resolve-Path (Join-Path $here "..\..")).Path
$build = Join-Path $here "build"
New-Item -ItemType Directory -Force -Path $build | Out-Null

$version = (Select-String -Path (Join-Path $root "server.py") -Pattern '^VERSION = "(.+)"').Matches[0].Groups[1].Value
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found: winget install JRSoftware.InnoSetup" }

# uv, the same as installer\install.ps1: its version and SHA-256 come from there.
$installer = Get-Content (Join-Path $root "installer\install.ps1") -Raw
$uvVersion = [regex]::Match($installer, '\$UvVersion = "([^"]+)"').Groups[1].Value
$uvSha = [regex]::Match($installer, '"x86_64"\s*=\s*"([0-9a-f]{64})"').Groups[1].Value
$uv = Join-Path $build "uv.exe"
if (-not ((Test-Path $uv) -and ((& $uv --version) -match [regex]::Escape($uvVersion)))) {
    Write-Host "  uv $uvVersion..."
    $zip = Join-Path $build "uv.zip"
    Invoke-WebRequest "https://github.com/astral-sh/uv/releases/download/$uvVersion/uv-x86_64-pc-windows-msvc.zip" -OutFile $zip -UseBasicParsing
    if ((Get-FileHash $zip -Algorithm SHA256).Hash.ToLower() -ne $uvSha) { throw "uv does not match its checksum" }
    Expand-Archive $zip -DestinationPath (Join-Path $build "uv") -Force
    Copy-Item (Get-ChildItem (Join-Path $build "uv") -Recurse -Filter "uv.exe" | Select-Object -First 1).FullName $uv -Force
    Remove-Item $zip, (Join-Path $build "uv") -Recurse -Force
}

Write-Host "  pictures..."
& $uv run --quiet --no-project --python 3.12 --with pillow python (Join-Path $here "art.py") $build
if ($LASTEXITCODE -ne 0) { throw "drawing the pictures failed" }

# Sottovoce with a console, for options such as --lan. %USERPROFILE% rather
# than a path: cmd reads a .cmd in the console's code page.
Set-Content (Join-Path $build "Sottovoce.cmd") -Encoding Ascii -Value @(
    "@echo off",
    "call `"%~dp0app\installer\start.cmd`" --data `"%USERPROFILE%\Sottovoce\transcripts`" --glossary `"%USERPROFILE%\Sottovoce\glossary.txt`" %*"
)

Write-Host "  Sottovoce $version..."
& $iscc /Q "/DVersion=$version" "/DRoot=$root" "/DBuild=$build" (Join-Path $here "Sottovoce.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
$exe = Join-Path $root "dist\Sottovoce-Setup-$version.exe"
Write-Host ("  built: {0} ({1:N1} MB)" -f $exe, ((Get-Item $exe).Length / 1MB))
