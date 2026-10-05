; Inno Setup script for Isocline Desktop.
; Build (after PyInstaller has produced dist\Isocline):
;     iscc /DAppVersion=3.3.0 packaging\desktop\installer.iss
; Output: dist\installer\Isocline-Setup-<version>.exe
;
; Installs per user by default (no administrator prompt); users can choose "install for all users" instead.
; User data (%LOCALAPPDATA%\Isocline: database, uploads, secrets, logs) is kept on uninstall and upgrade.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Isocline"
#define AppExe "Isocline.exe"
#define SourceDir "..\..\dist\Isocline"

[Setup]
AppId={{6E3B7C41-2F8D-4C5E-9B1A-7D0E4F2A9C63}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Isocline
AppPublisherURL=https://github.com/medhaja/isocline
AppSupportURL=https://github.com/medhaja/isocline/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\..\dist\installer
OutputBaseFilename=Isocline-Setup-{#AppVersion}
SetupIconFile=isocline.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Close a running Isocline before upgrading or uninstalling.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Remove files from the previous version so stale modules never mix with new ones.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[UninstallRun]
; Remove the Python sandbox's AppContainer profile (created on first use).
Filename: "{app}\{#AppExe}"; Parameters: "--remove-sandbox-profile"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveSandboxProfile"

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
