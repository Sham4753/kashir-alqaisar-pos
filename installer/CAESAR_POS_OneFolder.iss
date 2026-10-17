; CAESAR POS - OneFolder Installer
; Build this file on Windows with Inno Setup after running Build_CAESAR_OneFolder.bat.

#define ProductName "CAESAR POS"
#define ProductVersion "6.0.0"
#define PublisherName "CAESAR POS"
#define ExecutableName "CAESAR_POS.exe"
#define SourceFolder "..\dist\CAESAR_POS"

[Setup]
AppId={{B7E0A7B6-CAESAR-POS-V6-ONEDIR}
AppName={#ProductName}
AppVersion={#ProductVersion}
AppPublisher={#PublisherName}
DefaultDirName={localappdata}\CAESAR POS
DefaultGroupName={#ProductName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\installer_output
OutputBaseFilename=CAESAR_POS_Installer_v6
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#ExecutableName}
SetupIconFile=..\app\caesar_icon.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; Copy the complete OneFolder output, including _internal and all DLL files.
Source: "{#SourceFolder}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#ProductName}"; Filename: "{app}\{#ExecutableName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#ProductName}"; Filename: "{app}\{#ExecutableName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#ExecutableName}"; Description: "Launch {#ProductName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove only generated logs/cache in the installation directory.
; Do not remove customer data or the external CAESAR_Vault directory.
Type: files; Name: "{app}\caesar_server_error.log"
Type: files; Name: "{app}\caesar_desktop_error.log"

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
  if not FileExists(ExpandConstant('{#SourceFolder}\{#ExecutableName}')) then
  begin
    MsgBox('CAESAR_POS.exe was not found. Build the OneFolder output first.', mbCriticalError, MB_OK);
    Result := False;
  end;
end;
