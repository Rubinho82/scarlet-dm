; Instalador alternativo do Scarlet DM com Inno Setup 6 (o oficial é o installer\setup.py -> Setup.exe).
; Gere antes a pasta dist\ScarletDM com build_exe.bat; depois: build_exe.bat installer
; (ou abra este arquivo no Inno Setup e clique em Compile).

#define AppName "Scarlet DM"
#define AppVersion "2.0.0"
#define AppExe "ScarletDM.exe"

[Setup]
AppId={{6F2B7C1E-5D3A-4B8E-9C21-5CA7D0E1F9A4}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Scarlet DM
DefaultDirName={localappdata}\Programs\Scarlet DM
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Instala só para o usuário atual por padrão (sem pedir administrador); dá para escolher "todos os usuários".
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=ScarletDM-{#AppVersion}-setup
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "Iniciar com o Windows (minimizado na bandeja)"; GroupDescription: "Opções:"; Flags: unchecked

[Files]
Source: "..\dist\ScarletDM\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Pasta da extensão do navegador"; Filename: "{app}\extension"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Mesmo valor que o app grava em Preferências > Iniciar com o Windows (scarlet/autostart.py).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ScarletDM"; ValueData: """{app}\{#AppExe}"" --tray"; Tasks: autostart; Flags: uninsdeletevalue
; Remove o valor ao desinstalar mesmo se foi ligado pelo próprio app.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "ScarletDM"; Flags: uninsdeletevalue dontcreatekey

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/c taskkill /im {#AppExe} /f"; Flags: runhidden; RunOnceId: "KillScarlet"
