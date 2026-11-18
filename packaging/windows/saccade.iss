; Inno Setup script for the Saccade Windows installer.
; Built by .github/workflows/windows.yml, which passes the version in:
;   iscc /DAppVersion=0.9.1 packaging\windows\saccade.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "Saccade"
#define AppPublisher "Kiavash"
#define AppURL "https://github.com/khodekia/Saccade"
#define AppExeName "Saccade.exe"

[Setup]
AppId={{8F3A6C21-5B7E-4E62-9C0D-2A1F7D4B9E55}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Per-user install by default: no administrator password needed.
PrivilegesRequiredOverridesAllowed=dialog
PrivilegesRequired=lowest
; Paths below are relative to the repository root, not to this script.
SourceDir=..\..
OutputDir=dist
OutputBaseFilename=Saccade-{#AppVersion}-setup
SetupIconFile=packaging\windows\saccade.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "associatepdf"; Description: "Open &PDF files with Saccade"; GroupDescription: "File types:"; Flags: unchecked

[Files]
; The whole PyInstaller output folder, Qt and PyMuPDF included.
Source: "dist\Saccade\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; Offer Saccade in "Open with" for PDFs, without stealing the default.
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\shell\open\command"; \
    ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; \
    Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\.pdf\OpenWithProgids"; \
    ValueType: string; ValueName: "Saccade.Document"; ValueData: ""; \
    Flags: uninsdeletevalue; Tasks: associatepdf
Root: HKCU; Subkey: "Software\Classes\Saccade.Document"; \
    ValueType: string; ValueName: ""; ValueData: "PDF Document"; \
    Flags: uninsdeletekey; Tasks: associatepdf
Root: HKCU; Subkey: "Software\Classes\Saccade.Document\DefaultIcon"; \
    ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExeName},0"; \
    Tasks: associatepdf
Root: HKCU; Subkey: "Software\Classes\Saccade.Document\shell\open\command"; \
    ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; \
    Tasks: associatepdf

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Start {#AppName}"; \
    Flags: nowait postinstall skipifsilent
