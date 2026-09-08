#ifndef SourceDir
  #define SourceDir "..\dist\Clover"
#endif
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#ifndef IconFile
  #define IconFile "..\build\native\Clover.ico"
#endif

[Setup]
AppId={{CCF355A2-21EC-4B21-B8F8-077410C338B2}
AppName=Clover
AppVersion={#AppVersion}
AppPublisher=Clover
DefaultDirName={localappdata}\Programs\Clover
DefaultGroupName=Clover
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=Clover-Windows-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\Clover.exe
CloseApplications=yes

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Clover"; Filename: "{app}\Clover.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Clover"; Filename: "{app}\Clover.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\Clover.exe"; Description: "Open Clover"; Flags: nowait postinstall skipifsilent
