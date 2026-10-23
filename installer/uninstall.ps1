# Removes Sottovoce installed by install.ps1: the program folder, the
# shortcuts, the entry in Settings > Apps and the start with Windows.
# Settings > Apps > Sottovoce > Uninstall runs it; so can you.
#
# Then it asks, in two Windows dialogs, whether to delete what is yours too:
# the calls, and the models it downloaded. Yes to both leaves the computer
# as it was before Sottovoce. No is the answer already chosen: the calls are
# recordings of clients, and can't be recovered.
#
#     -Keep     no questions, keep the calls and the models (for scripts and tests)
param([switch]$Keep)

$ErrorActionPreference = "Stop"
$Program = Split-Path -Parent $MyInvocation.MyCommand.Path
$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Sottovoce"
$it = (Get-UICulture).TwoLetterISOLanguageName -eq "it"
function Say($en, $itText) { if ($it) { $itText } else { $en } }

Write-Host ""
Write-Host "  $(Say 'Removing Sottovoce from' 'Rimuovo Sottovoce da') $Program"
$running = $true
try { Invoke-WebRequest "http://127.0.0.1:8200/health" -UseBasicParsing -TimeoutSec 2 | Out-Null } catch { $running = $false }
if ($running) {
    Write-Host "  $(Say 'Sottovoce is running: quit it (right-click its icon by the clock, then Quit), then uninstall again.' 'Sottovoce è aperto: chiudilo (tasto destro sulla sua icona vicino all''orologio, poi Esci), poi disinstalla di nuovo.')" -ForegroundColor Red
    Start-Sleep 5
    return
}

# Where the calls are: the installer wrote it down, as it may not be the default.
$Data = Join-Path $env:USERPROFILE "Sottovoce"
$where = Join-Path $Program "data-folder.txt"
if (Test-Path $where) { $Data = (Get-Content $where -Raw).Trim() }
# Sottovoce's own models only, not the whole cache: other programs may use it.
$hub = if ($env:HF_HOME) { Join-Path $env:HF_HOME "hub" } else { Join-Path $env:USERPROFILE ".cache\huggingface\hub" }
$models = "models--openai--whisper-large-v3", "models--Qwen--Qwen3-4B-Instruct-2507" |
    ForEach-Object { Join-Path $hub $_ } | Where-Object { Test-Path $_ }

$dropCalls = $false
$dropModels = $false
if (-not $Keep) {
    Add-Type -AssemblyName System.Windows.Forms
    $yesNo = [System.Windows.Forms.MessageBoxButtons]::YesNo
    $no = [System.Windows.Forms.MessageBoxDefaultButton]::Button2
    if (Test-Path $Data) {
        $dropCalls = [System.Windows.Forms.MessageBox]::Show(
            (Say "Delete your calls too, recordings and transcripts, in $Data`?`n`nThey can't be recovered. No keeps them." `
                 "Eliminare anche le tue call, registrazioni e trascrizioni, in $Data`?`n`nNon si possono recuperare. No le tiene."),
            "Sottovoce", $yesNo, [System.Windows.Forms.MessageBoxIcon]::Warning, $no) -eq "Yes"
    }
    if ($models) {
        $gb = [math]::Round((($models | ForEach-Object { Get-ChildItem $_ -Recurse -File -Force -ErrorAction SilentlyContinue } |
            Measure-Object Length -Sum).Sum) / 1GB, 1)
        $dropModels = [System.Windows.Forms.MessageBox]::Show(
            (Say "Delete the models Sottovoce downloaded too (Whisper, and the one for summaries: $gb GB)?`n`nInstalling again downloads them again." `
                 "Eliminare anche i modelli scaricati da Sottovoce (Whisper e quello dei riassunti: $gb GB)?`n`nReinstallando si riscaricano."),
            "Sottovoce", $yesNo, [System.Windows.Forms.MessageBoxIcon]::Question, $no) -eq "Yes"
    }
}

foreach ($folder in [Environment]::GetFolderPath("Programs"), [Environment]::GetFolderPath("Desktop")) {
    Remove-Item (Join-Path $folder "Sottovoce.lnk") -Force -ErrorAction SilentlyContinue
}
Remove-Item $key -Recurse -Force -ErrorAction SilentlyContinue
# "Start with Windows", if it was ticked.
Remove-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name Sottovoce -ErrorAction SilentlyContinue
# Out of the folder first: Windows won't delete the folder a process stands in.
Set-Location $env:TEMP
Remove-Item $Program -Recurse -Force
if ($dropCalls) { Remove-Item $Data -Recurse -Force }
if ($dropModels) { $models | ForEach-Object { Remove-Item $_ -Recurse -Force } }

Write-Host ""
Write-Host "  $(Say 'Done.' 'Fatto.')"
if (Test-Path $Data) { Write-Host "  $(Say 'Your calls and glossary are still in' 'Le tue call e il glossario sono ancora in') $Data" }
if ($models -and -not $dropModels) { Write-Host "  $(Say 'The models are still in' 'I modelli sono ancora in') $hub" }
if ($dropCalls -and ($dropModels -or -not $models)) { Write-Host "  $(Say 'Nothing of Sottovoce is left on this computer.' 'Di Sottovoce non è rimasto niente su questo computer.')" }
Write-Host ""
if (-not $Keep) { Start-Sleep 5 }
