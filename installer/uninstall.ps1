# Removes Sottovoce installed by install.ps1: the program folder, the
# shortcuts and the entry in Settings > Apps. Your calls stay where they are.
# Settings > Apps > Sottovoce > Uninstall runs it; so can you.

$ErrorActionPreference = "Stop"
$Program = Split-Path -Parent $MyInvocation.MyCommand.Path
$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Sottovoce"

Write-Host ""
Write-Host "  Removing Sottovoce from $Program"
try {
    Invoke-WebRequest "http://127.0.0.1:8200/health" -UseBasicParsing -TimeoutSec 2 | Out-Null
    Write-Host "  Sottovoce is running: stop it (the power button on the page), then uninstall again." -ForegroundColor Red
    Start-Sleep 5
    return
} catch { }

foreach ($folder in [Environment]::GetFolderPath("Programs"), [Environment]::GetFolderPath("Desktop")) {
    Remove-Item (Join-Path $folder "Sottovoce.lnk") -Force -ErrorAction SilentlyContinue
}
Remove-Item $key -Recurse -Force -ErrorAction SilentlyContinue
# Out of the folder first: Windows won't delete the folder a process stands in.
Set-Location $env:TEMP
Remove-Item $Program -Recurse -Force

Write-Host ""
Write-Host "  Done. Your calls and glossary are still in $(Join-Path $env:USERPROFILE 'Sottovoce'), unless you chose another folder."
Write-Host "  The models (about 11 GB) are in $(Join-Path $env:USERPROFILE '.cache\huggingface'): delete it too if nothing else uses it."
Write-Host ""
Start-Sleep 5
