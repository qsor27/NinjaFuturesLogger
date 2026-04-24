; NinjaFuturesLogger installer — Inno Setup 6 script
; Per-user install, no UAC.

#define MyAppName        "NinjaFuturesLogger"
; MyAppVersion is normally supplied by build-installer.ps1 via
;   iscc /DMyAppVersion=v1.2.3 installer.iss
; Fall back to a placeholder for direct manual compiles.
#ifndef MyAppVersion
  #define MyAppVersion   "0.0.0-dev"
#endif
#define MyAppPublisher   "qsor27"
#define MyAppExeName     "NinjaFuturesLogger.exe"
#define MyAppId          "{{NFL-2CAE-4A1B-B1C1-6D9A28E}}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DisableDirPage=no
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
OutputBaseFilename=NinjaFuturesLogger-Setup-{#MyAppVersion}
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\payload\NinjaFuturesLogger.exe";                    DestDir: "{app}";               Flags: ignoreversion
Source: "..\payload\python\*";                                  DestDir: "{app}\python";        Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\payload\site-packages\*";                           DestDir: "{app}\site-packages"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\payload\app\*";                                     DestDir: "{app}\app";           Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\payload\ninjascript\*";                             DestDir: "{app}\ninjascript";   Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\payload\externals\MicrosoftEdgeWebview2Setup.exe";  DestDir: "{tmp}";               Flags: deleteafterinstall

[Icons]
Name: "{group}\{#MyAppName}";              Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}";    Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}";        Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Registry]
; Launcher reads HKCU\Software\NinjaFuturesLogger\DataDir at startup.
Root: HKCU; Subkey: "Software\NinjaFuturesLogger"; ValueType: string; ValueName: "DataDir"; ValueData: "{code:GetDataDir}"; Flags: uninsdeletevalue

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Installing Microsoft Edge WebView2 Runtime..."; Check: NeedsWebView2
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\*"
Type: dirifempty; Name: "{app}"

#include "pages.pas"
