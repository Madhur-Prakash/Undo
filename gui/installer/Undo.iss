; Undo installer, for Inno Setup 7.
;
; Open this file in Inno Setup and choose Build > Compile (or run: ISCC Undo.iss).
; Compiling does everything:
;   1. installs Undo's Python packages into the repository's virtual environment (uv sync),
;   2. builds the backend with PyInstaller (Undo.spec) into build\dist\backend:
;      undo.exe (command line and TUI) and undo-daemon.exe (the daemon, no console window),
;   3. builds the desktop app, Undo.exe, with Flutter (gui\undo_desktop),
;   4. packs both into Undo-Setup-<version>.exe here.
; The first compile takes several minutes. Each step writes its output to a log in
; build\ (uv.log, pyinstaller.log, flutter.log), named in the error if a step fails.
;
; Needs on this machine: uv (https://docs.astral.sh/uv/) and Flutter with Visual Studio's
; "Desktop development with C++" workload. uv fetches Python 3.12 itself if needed.
;
; Options (ISCC /D<name>=<value>, or edit the #define lines below):
;   Uv        uv.exe to build with                  default: ~\.local\bin\uv.exe, else uv on PATH
;   Flutter   flutter.bat (full path)               default: found on PATH
;   BuildApp  0 = package the existing builds       default: 1

#ifndef Uv
  #if FileExists(GetEnv("USERPROFILE") + "\.local\bin\uv.exe")
    #define Uv GetEnv("USERPROFILE") + "\.local\bin\uv.exe"
  #else
    #define Uv "uv"
  #endif
#endif
; flutter.bat must be run by its full path: called as a quoted bare "flutter", cmd gives
; it the wrong %~dp0 and it fails with "The Flutter directory is not a clone".
; The preprocessor can't search PATH (FileSearch exists only in [Code]), so walk it one
; folder at a time: set PathName, then "#for {...} PathStep" leaves the match in PathHit.
#define PathName ""
#define PathRest ""
#define PathDir ""
#define PathHit ""
#sub PathStep
  #expr PathDir = Trim(StringChange(Copy(PathRest, 1, Pos(";", PathRest) - 1), '"', ""))
  #expr PathRest = Copy(PathRest, Pos(";", PathRest) + 1, Len(PathRest))
  #if PathDir != "" && FileExists(AddBackslash(PathDir) + PathName)
    #expr PathHit = AddBackslash(PathDir) + PathName
  #endif
#endsub
#ifndef Flutter
  #expr PathName = "flutter.bat", PathRest = GetEnv("PATH") + ";", PathHit = ""
  #for {0; PathHit == "" && Len(PathRest) > 0; 0} PathStep
  #if PathHit == ""
    #error flutter.bat was not found on PATH: install Flutter, or compile with /DFlutter=C:\path\to\flutter\bin\flutter.bat
  #endif
  #define Flutter PathHit
#endif
#ifndef BuildApp
  #define BuildApp 1
#endif
; ISCC /DBuildApp=0 arrives as the text "0", which #if would take as true.
#define BuildApp Int(BuildApp, 1)

#define AppName "Undo"
#define AppExe "Undo.exe"
#define CliExe "undo.exe"
#define DaemonExe "undo-daemon.exe"
#define AppPublisher "Undo contributors"
#define AppUrl "https://github.com/Madhur-Prakash/Undo"
; Held by the running desktop app (windows\runner\main.cpp), so Setup can ask to close it.
#define AppMutexName "UndoDesktopRunning"

#define Here RemoveBackslashUnlessRoot(SourcePath)
; This file sits in <repository>\gui\installer.
#define GuiDir ExtractFileDir(Here)
#define Root ExtractFileDir(GuiDir)
#define DesktopDir GuiDir + "\undo_desktop"
#define BuildDir Here + "\build"
#define BackendDir BuildDir + "\dist\backend"
#define FlutterOut DesktopDir + "\build\windows\x64\runner\Release"
#define Cmd GetEnv("ComSpec")
#define SW_HIDE 0

; ---- 1-3: build the backend and the desktop app ---------------------------------------

#if BuildApp
  #pragma message "Undo: building with " + Uv + " and " + Flutter
  #expr Exec(Cmd, '/S /C "if not exist "' + BuildDir + '" mkdir "' + BuildDir + '""', Here, 1, SW_HIDE)

  #pragma message "Undo: installing the Python packages (log: build\uv.log)..."
  #if Exec(Cmd, '/S /C ""' + Uv + '" sync --all-packages --frozen > "' + BuildDir + '\uv.log" 2>&1"', Root, 1, SW_HIDE) != 0
    #error uv sync failed: see build\uv.log, or set Uv to a working uv.exe.
  #endif

  #pragma message "Undo: building undo.exe and undo-daemon.exe with PyInstaller, a few minutes (log: build\pyinstaller.log)..."
  #if Exec(Cmd, '/S /C ""' + Uv + '" run --all-packages --frozen --with "pyinstaller>=6.10" pyinstaller --noconfirm --clean --distpath "' + BuildDir + '\dist" --workpath "' + BuildDir + '\work" "' + Here + '\Undo.spec" > "' + BuildDir + '\pyinstaller.log" 2>&1"', Root, 1, SW_HIDE) != 0
    #error PyInstaller could not build the backend: see build\pyinstaller.log.
  #endif

  #pragma message "Undo: building Undo.exe with Flutter, a few minutes (log: build\flutter.log)..."
  #if Exec(Cmd, '/S /C ""' + Flutter + '" build windows --release > "' + BuildDir + '\flutter.log" 2>&1"', DesktopDir, 1, SW_HIDE) != 0
    #error Flutter could not build the desktop app: see build\flutter.log.
  #endif
#endif

#if !FileExists(BackendDir + "\" + CliExe) || !FileExists(BackendDir + "\" + DaemonExe)
  #error build\dist\backend is missing undo.exe or undo-daemon.exe. Compile with BuildApp=1 to build it.
#endif
#define AppExePath FlutterOut + "\" + AppExe
#if !FileExists(AppExePath)
  #error gui\undo_desktop\build\windows\x64\runner\Release\Undo.exe is missing. Compile with BuildApp=1 to build it.
#endif
; Flutter stamps the pubspec version ("1.0.0+1"); Setup shows the part before "+".
#define RawVersion GetStringFileInfo(AppExePath, "ProductVersion")
#define AppVersion Pos("+", RawVersion) > 0 ? Copy(RawVersion, 1, Pos("+", RawVersion) - 1) : RawVersion

[Setup]
AppId={{2D813CA8-FF27-425D-B53B-1C333CFCA7BF}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
AppMutex={#AppMutexName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Undo is per user: its history lives in %LOCALAPPDATA%\Undo and its daemon runs as you.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile={#Root}\LICENSE
SetupIconFile={#GuiDir}\assets\undo.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
OutputDir={#Here}
OutputBaseFilename=Undo-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
ChangesEnvironment=yes
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup

[Tasks]
Name: "startup"; Description: "Start the Undo daemon when I sign in (keeps recording changes in the background)"
Name: "addtopath"; Description: "Add the undo command to PATH (for the terminal and the TUI)"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; An upgrade replaces the programs rather than copying over them, so no stale library
; from an older build is loaded. Version history is not here: it is in %LOCALAPPDATA%\Undo.
Type: filesandordirs; Name: "{app}\backend\_internal"
Type: filesandordirs; Name: "{app}\data"

[Files]
Source: "{#FlutterOut}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#BackendDir}\*"; DestDir: "{app}\backend"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Root}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} (terminal dashboard)"; Filename: "{app}\backend\{#CliExe}"; Parameters: "tui"; WorkingDir: "{userdocs}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; The autostart value `undo service install` writes: removed on uninstall even if the
; daemon's own `service uninstall` could not run.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "Undo"; Flags: uninsdeletevalue dontcreatekey
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}\backend"; Check: NeedsAddPath(ExpandConstant('{app}\backend')); Tasks: addtopath

[Run]
; Creates %LOCALAPPDATA%\Undo (settings, database, API token) if this is the first install.
Filename: "{app}\backend\{#CliExe}"; Parameters: "init"; StatusMsg: "Preparing Undo's data folder..."; Flags: runhidden waituntilterminated
; Starts undo-daemon.exe at every sign-in through the per-user Run key (value "Undo"; no
; administrator rights needed), and starts it now. The same as `undo service install`.
Filename: "{app}\backend\{#CliExe}"; Parameters: "service install"; StatusMsg: "Registering the Undo daemon to start at sign-in..."; Flags: runhidden waituntilterminated; Tasks: startup
Filename: "{app}\{#AppExe}"; Description: "Start Undo now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\backend\{#CliExe}"; Parameters: "stop"; Flags: runhidden waituntilterminated; RunOnceId: "StopDaemon"
Filename: "{app}\backend\{#CliExe}"; Parameters: "service uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveLogonTask"
Filename: "{sys}\taskkill.exe"; Parameters: "/IM {#DaemonExe} /F"; Flags: runhidden; RunOnceId: "KillDaemon"
Filename: "{sys}\taskkill.exe"; Parameters: "/IM {#AppExe} /F"; Flags: runhidden; RunOnceId: "KillApp"

[Messages]
FinishedLabel=Undo is installed.%n%nOpen Undo, choose a folder to track, and every change to its files is kept: browse a file's history and restore any earlier version, or bring back deleted files.

[Code]
const
  EnvKey = 'Environment';

function NeedsAddPath(Dir: string): Boolean;
var
  Current: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, EnvKey, 'Path', Current) then
    Current := '';
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Current) + ';') = 0;
end;

procedure RemoveFromPath(Dir: string);
var
  Current, Upper, Needle: string;
  P: Integer;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, EnvKey, 'Path', Current) then
    exit;
  Current := ';' + Current + ';';
  Needle := ';' + Uppercase(Dir) + ';';
  Upper := Uppercase(Current);
  P := Pos(Needle, Upper);
  if P = 0 then
    exit;
  Delete(Current, P, Length(Needle) - 1);
  Current := Copy(Current, 2, Length(Current) - 2);
  RegWriteExpandStringValue(HKEY_CURRENT_USER, EnvKey, 'Path', Current);
end;

// On upgrade the old daemon still runs from {app}\backend and holds its files open:
// stop it gracefully (it finishes pending captures) before files are replaced.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  OldCli: string;
  Code: Integer;
begin
  Result := '';
  OldCli := ExpandConstant('{app}\backend\{#CliExe}');
  if FileExists(OldCli) then
  begin
    Exec(OldCli, 'stop', '', SW_HIDE, ewWaitUntilTerminated, Code);
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM {#DaemonExe} /F', '', SW_HIDE, ewWaitUntilTerminated, Code);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: string;
begin
  if CurUninstallStep <> usPostUninstall then
    exit;
  RemoveFromPath(ExpandConstant('{app}\backend'));
  DataDir := GetEnv('UNDO_HOME');
  if DataDir = '' then
    DataDir := ExpandConstant('{localappdata}\Undo');
  if DirExists(DataDir) and not UninstallSilent then
    if MsgBox('Also delete Undo''s version history in' + #13#10 + DataDir + '?' + #13#10#13#10 +
              'Choose No to keep it: reinstalling Undo picks it up again.',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(DataDir, True, True, True);
end;
