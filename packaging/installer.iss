; Windows installer of one edition, compiled by packaging/installer.py (Inno Setup 6).
; Per-user install (no administrator rights) in %LOCALAPPDATA%\Programs\<AppName>, so that the app can update itself.
; Profile, history and stats live in %LOCALAPPDATA%\<AppName>\data and are kept on uninstall.
;
; Defines: AppName, AppExe, AppVersion, AppNumVersion (x.y.z.w), AppGuid, SourceDir, OutputDir, OutputBase, SmallImages

[Setup]
AppId={{{#AppGuid}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Raktos
AppPublisherURL=https://raktos1030.github.io/Roulette-of-Legends/
AppSupportURL=https://github.com/Raktos1030/Roulette-of-Legends
AppUpdatesURL=https://github.com/Raktos1030/Roulette-of-Legends/releases/latest
VersionInfoVersion={#AppNumVersion}
VersionInfoProductName={#AppName}
VersionInfoCompany=Raktos
DefaultDirName={localappdata}\Programs\{#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBase}
SetupIconFile={#SourceDir}\data\img\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardSmallImageFile={#SmallImages}
Compression=lzma2/max
SolidCompression=yes
CloseApplications=force
ShowLanguageDialog=auto
LanguageDetectionMethod=uilanguage

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; program files of a previous version (not data\, which may still hold an older version's profile)
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\ui"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /t /im ""{#AppExe}"""; Flags: runhidden; RunOnceId: "StopApp"

[UninstallDelete]
; files replaced or added by in-app updates since the install
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\ui"
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\*.old"

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Command: String;
begin
  { start with Windows: entry written by the app itself, removed only when it starts this installation
    (another copy of the app may own it) }
  if (CurUninstallStep = usUninstall) and RegQueryStringValue(HKEY_CURRENT_USER, RunKey, '{#AppName}', Command) then
    if Pos(Lowercase(ExpandConstant('{app}')), Lowercase(Command)) > 0 then
      RegDeleteValue(HKEY_CURRENT_USER, RunKey, '{#AppName}');
end;
