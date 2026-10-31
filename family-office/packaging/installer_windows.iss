; ==============================================================================
; Inno Setup Script for HVL Family Office (Windows 10 / 11 Installer)
; - Installs without requiring Administrator elevation (PrivilegesRequired=lowest)
; - Creates Start Menu and Desktop shortcuts ("HVL Family Office")
; - Automatically launches HVL-Family-Office.exe at the end of installation,
;   which starts the local encrypted server and pops open the user's browser!
; ==============================================================================

#define MyAppName "HVL Family Office"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "High Velocity Labs"
#define MyAppURL "https://finances.highvelocitylabs.dev"
#define MyAppExeName "HVL-Family-Office.exe"

[Setup]
AppId={{8F9B3A21-6C4E-4A9D-9E12-7D3A5B8C1F40}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=HVL-Family-Office-Setup
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\HVL-Family-Office\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\HVL-Family-Office\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Immediately launch HVL Family Office after install so the user's browser opens automatically
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
