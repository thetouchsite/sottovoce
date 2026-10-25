; Sottovoce for Windows: the setup. Built by build.ps1 into dist\.
;
; Per user, no administrator rights, in the same folder as the one-command
; install (installer\install.ps1), which it takes over. The setup copies the
; program and uv; then prepare.ps1 brings Python and the PyTorch that sees
; this computer's GPU, with a progress page. The models come later, when
; first used, after asking. Uninstalling asks about the calls and the models.

#ifndef Version
  #define Version "0.0.0"
#endif
#ifndef Root
  #define Root "..\.."
#endif
#ifndef Build
  #define Build "build"
#endif

[Setup]
; Fixed: every new version installs over the one before, never beside it.
AppId={{E5143744-8D12-40A0-901B-842135560252}
AppName=Sottovoce
AppVersion={#Version}
AppVerName=Sottovoce {#Version}
AppPublisher=TouchSite Software
AppPublisherURL=https://www.touchsitesoftware.it/
AppSupportURL=https://github.com/thetouchsite/sottovoce/issues
AppUpdatesURL=https://github.com/thetouchsite/sottovoce/releases
AppContact=info@touchsitesoftware.it
AppCopyright=© 2026 TouchSite Software
AppComments=Calls, transcribed on your computer
VersionInfoVersion={#Version}
VersionInfoCompany=TouchSite Software
VersionInfoDescription=Sottovoce Setup
VersionInfoProductName=Sottovoce
VersionInfoProductVersion={#Version}
VersionInfoProductTextVersion={#Version}
VersionInfoCopyright=© 2026 TouchSite Software
DefaultDirName={localappdata}\Programs\Sottovoce
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableWelcomePage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
SetupIconFile={#Root}\app\icon.ico
WizardImageFile={#Build}\wizard-1x.bmp,{#Build}\wizard-2x.bmp
WizardSmallImageFile={#Build}\small-1x.bmp,{#Build}\small-2x.bmp
UninstallDisplayIcon={app}\app\app\icon.ico
UninstallDisplayName=Sottovoce
OutputDir={#Root}\dist
OutputBaseFilename=Sottovoce-Setup-{#Version}
Compression=lzma2/max
SolidCompression=yes
; Sottovoce holds this mutex while it runs (desktop.py, MUTEX): the setup and
; the uninstall ask to quit it first, instead of failing on files in use.
AppMutex=TouchSiteSottovoce
CloseApplications=no
; What prepare.ps1 adds after the copy: Python, PyTorch, the packages.
ExtraDiskSpaceRequired=3500000000
ShowLanguageDialog=no
LanguageDetectionMethod=uilanguage
SetupLogging=yes
; Inno turns on Windows' RedirectionGuard by default, and the programs it
; runs inherit it: uv could not use the folder link it makes for Python
; (os error 448, "untrusted mount point"), and the setup failed every time.
; It guards an elevated setup against links planted by other users; this
; one runs for one user, without elevation, in that user's own folder.
RedirectionGuard=no

[Languages]
; English first: a Windows in neither language gets English.
Name: "en"; MessagesFile: "compiler:Default.isl"; LicenseFile: "{#Root}\LICENSE"; InfoBeforeFile: "info-en.txt"
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"; LicenseFile: "{#Root}\LICENSE"; InfoBeforeFile: "info-it.txt"

[CustomMessages]
en.Desktop=Create a shortcut on the desktop
it.Desktop=Crea un collegamento sul desktop
en.Shortcuts=Shortcuts:
it.Shortcuts=Collegamenti:
en.ShortcutComment=Calls, transcribed on your computer
it.ShortcutComment=Trascrizione delle call, sul tuo computer
en.Launch=Start Sottovoce
it.Launch=Avvia Sottovoce
en.Preparing=Preparing Sottovoce
it.Preparing=Preparo Sottovoce
en.PreparingSub=Downloading what this computer needs. It can take a few minutes.
it.PreparingSub=Scarico quello che serve a questo computer. Può richiedere qualche minuto.
en.Starting=Getting ready
it.Starting=Preparazione
en.StepPython=Downloading Python
it.StepPython=Scarico Python
en.StepTorchGPU=Downloading PyTorch for your NVIDIA graphics card (about 2 GB)
it.StepTorchGPU=Scarico PyTorch per la tua scheda video NVIDIA (circa 2 GB)
en.StepTorchCPU=Downloading PyTorch for the processor (about 200 MB)
it.StepTorchCPU=Scarico PyTorch per il processore (circa 200 MB)
en.StepRest=Downloading the other components
it.StepRest=Scarico gli altri componenti
en.Elapsed=%1 s
it.Elapsed=%1 s
en.Failed=Sottovoce is installed, but preparing its components did not succeed:%n%n%1%n%nCheck the internet connection and run this setup again: what was already downloaded is kept. Details are in:%n%2
it.Failed=Sottovoce è installato, ma la preparazione dei componenti non è riuscita:%n%n%1%n%nControlla la connessione e avvia di nuovo questa installazione: quello che è già stato scaricato resta. I dettagli sono in:%n%2
en.AskCalls=Delete your calls too, recordings and transcripts, in:%n%1%n%nThey can't be recovered. Choose No to keep them: installing Sottovoce again finds them.
it.AskCalls=Eliminare anche le tue call, registrazioni e trascrizioni, in:%n%1%n%nNon si possono recuperare. Scegli No per tenerle: reinstallando Sottovoce le ritrovi.
en.AskModels=Delete the models Sottovoce downloaded too (Whisper, and the one for summaries: several GB)?%n%nChoose No if you will install Sottovoce again: they won't be downloaded again.
it.AskModels=Eliminare anche i modelli scaricati da Sottovoce (Whisper e quello dei riassunti: alcuni GB)?%n%nScegli No se reinstallerai Sottovoce: non andranno riscaricati.

[Tasks]
Name: "desktop"; Description: "{cm:Desktop}"; GroupDescription: "{cm:Shortcuts}"

[Files]
; The program: the code next to its .venv, as the one-command install lays it out.
; Every module at the top of the repository: a list by name once left one out.
Source: "{#Root}\*.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "{#Root}\requirements.txt"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "{#Root}\glossary.example.txt"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "{#Root}\app\*"; DestDir: "{app}\app\app"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Root}\installer\gpu.py"; DestDir: "{app}\app\installer"; Flags: ignoreversion
Source: "{#Root}\installer\start.cmd"; DestDir: "{app}\app\installer"; Flags: ignoreversion
; uv, at the version build.ps1 checked against its SHA-256; and what sets up the rest.
Source: "{#Build}\uv.exe"; DestDir: "{app}\bin"; Flags: ignoreversion
Source: "prepare.ps1"; DestDir: "{app}\setup"; Flags: ignoreversion
; Sottovoce with a console, for options such as --lan.
Source: "{#Build}\Sottovoce.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "THIRD-PARTY.txt"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; An update replaces the code, not .venv, the voice models or the phone PIN.
Type: files; Name: "{app}\app\*.py"
Type: filesandordirs; Name: "{app}\app\app"
Type: filesandordirs; Name: "{app}\app\installer"
; Left by the one-command install, which this setup takes over.
Type: files; Name: "{app}\uninstall.ps1"

[Icons]
Name: "{autoprograms}\Sottovoce"; Filename: "{app}\app\.venv\Scripts\pythonw.exe"; Parameters: """{app}\app\desktop.py"" --data ""{code:DataDir}\transcripts"" --glossary ""{code:DataDir}\glossary.txt"" --log ""{app}\sottovoce.log"""; WorkingDir: "{app}\app"; IconFilename: "{app}\app\app\icon.ico"; Comment: "{cm:ShortcutComment}"; AppUserModelID: "TouchSite.Sottovoce"
Name: "{autodesktop}\Sottovoce"; Filename: "{app}\app\.venv\Scripts\pythonw.exe"; Parameters: """{app}\app\desktop.py"" --data ""{code:DataDir}\transcripts"" --glossary ""{code:DataDir}\glossary.txt"" --log ""{app}\sottovoce.log"""; WorkingDir: "{app}\app"; IconFilename: "{app}\app\app\icon.ico"; Comment: "{cm:ShortcutComment}"; AppUserModelID: "TouchSite.Sottovoce"; Tasks: desktop

[Run]
Filename: "{app}\app\.venv\Scripts\pythonw.exe"; Parameters: """{app}\app\desktop.py"" --data ""{code:DataDir}\transcripts"" --glossary ""{code:DataDir}\glossary.txt"" --log ""{app}\sottovoce.log"""; WorkingDir: "{app}\app"; Description: "{cm:Launch}"; Flags: nowait postinstall skipifsilent; Check: Prepared
; An update installed by Sottovoce itself (updates.py) runs this setup
; silently with /RELAUNCH=1: Sottovoce starts again by itself afterwards. postinstall:
; run at the end, after prepare.ps1, as postinstall entries are in silent mode.
Filename: "{app}\app\.venv\Scripts\pythonw.exe"; Parameters: """{app}\app\desktop.py"" --data ""{code:DataDir}\transcripts"" --glossary ""{code:DataDir}\glossary.txt"" --log ""{app}\sottovoce.log"""; WorkingDir: "{app}\app"; Flags: nowait postinstall; Check: Relaunch

[UninstallDelete]
; Everything the program folder gained after the copy: Python, .venv, the
; download cache, the log, the window's storage.
Type: filesandordirs; Name: "{app}"

[Code]
// The milliseconds since Windows started: for the seconds shown while preparing.
function GetTickCount: DWord; external 'GetTickCount@kernel32.dll stdcall';

var
  PrepareDone: Boolean;
  UninstallData: String;

// Where the calls are kept: never in Documents, which OneDrive may copy to the cloud.
function DataDir(Param: String): String;
begin
  Result := ExpandConstant('{%USERPROFILE}') + '\Sottovoce';
end;

function Prepared(): Boolean;
begin
  Result := PrepareDone;
end;

function Relaunch(): Boolean;
begin
  Result := PrepareDone and WizardSilent and (ExpandConstant('{param:RELAUNCH|0}') = '1');
end;

// The one-command install wrote its own entry in Settings > Apps: this setup
// takes over the same folder, so one entry stays, its own.
procedure TakeOverCommandInstall();
begin
  RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\Sottovoce');
end;

function StepText(Word: String): String;
begin
  if Word = 'python' then
    Result := CustomMessage('StepPython')
  else if Word = 'torch:cpu' then
    Result := CustomMessage('StepTorchCPU')
  else if Pos('torch:', Word) = 1 then
    Result := CustomMessage('StepTorchGPU')
  else if Word = 'rest' then
    Result := CustomMessage('StepRest')
  else
    Result := CustomMessage('Starting');
end;

// prepare.ps1 runs hidden and writes one word per step in a file; the page
// shows the step in the user's language, a moving bar and the seconds, so a
// two-gigabyte download never looks stuck.
procedure Prepare();
var
  Page: TOutputProgressWizardPage;
  StatusFile, Word, Params: String;
  Raw: AnsiString;
  Code: Integer;
  Started: DWord;
begin
  StatusFile := ExpandConstant('{tmp}\prepare-status.txt');
  SaveStringToFile(StatusFile, 'starting', False);
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\setup\prepare.ps1') +
            '" -Program "' + ExpandConstant('{app}') + '" -Data "' + DataDir('') +
            '" -Status "' + StatusFile + '"';
  Page := CreateOutputProgressPage(CustomMessage('Preparing'), CustomMessage('PreparingSub'));
  Page.ProgressBar.Style := npbstMarquee;
  Page.Show;
  Word := 'starting';
  try
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params, '', SW_HIDE, ewNoWait, Code) then
      Word := 'error:' + SysErrorMessage(Code)
    else
    begin
      Started := GetTickCount;
      repeat
        Sleep(200);
        if LoadStringFromFile(StatusFile, Raw) then
          Word := Trim(String(Raw));
        Page.SetText(StepText(Word), FmtMessage(CustomMessage('Elapsed'), [IntToStr((GetTickCount - Started) div 1000)]));
      until (Word = 'done') or (Pos('error:', Word) = 1);
    end;
  finally
    Page.Hide;
  end;
  PrepareDone := Word = 'done';
  if not PrepareDone then
    SuppressibleMsgBox(FmtMessage(CustomMessage('Failed'), [Copy(Word, 7, Length(Word)), ExpandConstant('{app}\setup.log')]),
                       mbError, MB_OK, IDOK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    TakeOverCommandInstall()
  else if CurStep = ssPostInstall then
    Prepare();
end;

// Sottovoce's own models, not the whole cache: other programs may use it.
function Hub(): String;
begin
  Result := GetEnv('HF_HOME');
  if Result = '' then
    Result := ExpandConstant('{%USERPROFILE}') + '\.cache\huggingface';
  Result := Result + '\hub';
end;

// Sottovoce's own models in the Hugging Face cache, not the whole cache:
// other programs may use it. Whisper as PyTorch and as OpenVINO runs it,
// turbo if it was chosen, and the summary model.
const
  ModelCount = 5;

function Model(I: Integer): String;
begin
  case I of
    0: Result := 'models--openai--whisper-large-v3';
    1: Result := 'models--openai--whisper-large-v3-turbo';
    2: Result := 'models--OpenVINO--whisper-large-v3-int8-ov';
    3: Result := 'models--OpenVINO--whisper-large-v3-turbo-int8-ov';
    4: Result := 'models--Qwen--Qwen3-4B-Instruct-2507';
  end;
end;

// Uninstalling: the program goes; the calls and the models go only if the
// user says so, with No already chosen. Yes to both leaves the computer as
// it was before Sottovoce.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  I: Integer;
  Found: Boolean;
begin
  if CurUninstallStep = usUninstall then
  begin
    UninstallData := DataDir('');
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Sottovoce');
  end;
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
  begin
    if DirExists(UninstallData) then
      if MsgBox(FmtMessage(CustomMessage('AskCalls'), [UninstallData]), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(UninstallData, True, True, True);
    Found := False;
    for I := 0 to ModelCount - 1 do
      if DirExists(Hub() + '\' + Model(I)) then
        Found := True;
    if Found then
      if MsgBox(CustomMessage('AskModels'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        for I := 0 to ModelCount - 1 do
          DelTree(Hub() + '\' + Model(I), True, True, True);
  end;
end;
