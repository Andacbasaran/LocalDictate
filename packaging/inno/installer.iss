; LocalDictate — Inno Setup 6 Windows Installer Script (v1.0.0)
; Packages dist\LocalDictate\* into LocalDictate-Setup-v1.0.0-Windows-x64.exe
;
; Build:
;   python scripts/build_exe.py --skip-zip
;   iscc /DMyAppVersion=1.0.0 packaging\inno\installer.iss

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName "LocalDictate"
#define MyAppPublisher "Andac Basaran"
#define MyAppURL "https://localdictate.andacbasaran.com"
#define MyAppRepo "https://github.com/Andacbasaran/LocalDictate"
#define MyAppExeName "LocalDictate.exe"

[Setup]
AppId={{9B5C2F1E-42A8-4E6D-B193-7E4A62D0C8F1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppRepo}/issues
AppUpdatesURL={#MyAppRepo}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=LocalDictate-Setup-v{#MyAppVersion}-Windows-x64
SetupIconFile=..\..\assets\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
CloseApplications=force
RestartApplications=yes
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} — 100% Offline Desktop AI Dictation Studio
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\..\dist\LocalDictate\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#MyAppExeName}"; Flags: nowait skipifnotsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  UserDataDir: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    UserDataDir := ExpandConstant('{userappdata}\LocalDictate');
    if (not UninstallSilent) and DirExists(UserDataDir) then
    begin
      if MsgBox(
        'Do you also want to remove your LocalDictate settings, snippets, and SQLite dictation history (%APPDATA%\LocalDictate)?',
        mbConfirmation,
        MB_YESNO
      ) = IDYES then
      begin
        DelTree(UserDataDir, True, True, True);
      end;
    end;
  end;
end;
