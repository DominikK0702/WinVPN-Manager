#ifndef AppVersion
#define AppVersion "0.1.0"
#endif

#ifndef BuildInputDir
#define BuildInputDir "..\\dist\\WinVPN-Manager"
#endif

[Setup]
AppId={{A6C37552-9A5A-4FE9-B58B-C8BF6756A2FE}
AppName=WinVPN-Manager
AppVersion={#AppVersion}
AppPublisher=WinVPN-Manager
DefaultDirName={localappdata}\Programs\WinVPN-Manager
DefaultGroupName=WinVPN-Manager
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\WinVPN-Manager.exe
OutputDir=..\installer-output
OutputBaseFilename=WinVPN-Manager-Setup-{#AppVersion}

#ifexist "..\app\logo.ico"
SetupIconFile=..\app\logo.ico
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "{#BuildInputDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\WinVPN-Manager"; Filename: "{app}\WinVPN-Manager.exe"
Name: "{autodesktop}\WinVPN-Manager"; Filename: "{app}\WinVPN-Manager.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\WinVPN-Manager.exe"; Description: "Launch WinVPN-Manager"; Flags: nowait postinstall skipifsilent
