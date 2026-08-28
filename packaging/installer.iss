; Inno Setup 6 script for the AOPS Windows installer.
;
; Compiled by packaging/build.py --installer (which passes the version), or
; by hand from the repository root after a PyInstaller build:
;
;     ISCC packaging\installer.iss /DAppVersion=1.0.0
;
; Wraps the PyInstaller one-folder output (dist\AOPS) into a single
; AOPS-Setup-<version>.exe: Program Files install, Start-menu entry,
; optional desktop icon, .aops file association, clean uninstall.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7F3D9B42-6A1C-4E8F-9D25-C1A8B0E4F773}
AppName=AOPS
AppVersion={#AppVersion}
AppVerName=AOPS {#AppVersion}
AppPublisher=AOPS
DefaultDirName={autopf}\AOPS
DefaultGroupName=AOPS
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=AOPS-Setup-{#AppVersion}
SetupIconFile=aops.ico
UninstallDisplayIcon={app}\AOPS.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; Flags: unchecked
Name: "fileassoc"; Description: "Associate .aops project files with AOPS"

[Files]
Source: "..\dist\AOPS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\AOPS"; Filename: "{app}\AOPS.exe"
Name: "{group}\AOPS command line"; Filename: "{app}\aops-cli.exe"
Name: "{autodesktop}\AOPS"; Filename: "{app}\AOPS.exe"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.aops"; ValueType: string; ValueName: ""; ValueData: "AOPS.Project"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\AOPS.Project"; ValueType: string; ValueName: ""; ValueData: "AOPS position strip project"; Flags: uninsdeletekey; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\AOPS.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\AOPS.exe,0"; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\AOPS.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\AOPS.exe"" ""%1"""; Tasks: fileassoc

[Run]
Filename: "{app}\AOPS.exe"; Description: "Launch AOPS"; Flags: nowait postinstall skipifsilent
