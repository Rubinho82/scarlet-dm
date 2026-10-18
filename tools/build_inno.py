"""Gera o instalador do Windows com o Inno Setup: ScarletDM-<versão>-Setup.exe.

Por que Inno Setup: é o instalador usado por VS Code, Git, Python e milhares de programas, então os antivírus
o conhecem e não confundem com vírus (um Setup "tudo num .exe só" feito com PyInstaller é muito mais acusado).

Uso: python tools/build_inno.py PASTA_DO_APP PASTA_DE_SAIDA
Precisa do Inno Setup 6 (ISCC.exe): no PATH, na pasta padrão, em F:/tools/InnoSetup6 ou na variável ISCC.
O texto do instalador vem das traduções do próprio app (scarlet/locales).
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from scarlet import APP_NAME, VERSION  # noqa: E402

# nosso código de idioma -> arquivo de mensagens do Inno Setup
INNO_LANGS = {
    "en": "compiler:Default.isl", "pt_BR": "compiler:Languages\\BrazilianPortuguese.isl",
    "es": "compiler:Languages\\Spanish.isl", "fr": "compiler:Languages\\French.isl",
    "de": "compiler:Languages\\German.isl", "it": "compiler:Languages\\Italian.isl",
    "ru": "compiler:Languages\\Russian.isl", "tr": "compiler:Languages\\Turkish.isl",
    "ja": "compiler:Languages\\Japanese.isl", "ko": "compiler:Languages\\Korean.isl",
    "zh_CN": os.path.join(ROOT, "installer", "languages", "ChineseSimplified.isl"),
}
# mensagens próprias (chave = texto em português usado no app, já traduzido em scarlet/locales)
MESSAGES = {
    "AutoStart": "Iniciar com o Windows (minimizado perto do relógio)",
    "Magnet": "Abrir links magnet e arquivos .torrent com o Scarlet DM",
    "RemoveData": "Apagar também a lista de downloads, as configurações e os componentes de vídeo",
    "KeepFiles": "Os arquivos que você baixou não são apagados.",
    "Options": "Preferências",
}


def find_iscc():
    cands = [os.environ.get("ISCC", ""), shutil.which("ISCC") or "", r"F:\tools\InnoSetup6\ISCC.exe",
             os.path.expandvars(r"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"),
             os.path.expandvars(r"%ProgramFiles%\Inno Setup 6\ISCC.exe"),
             os.path.expandvars(r"%LocalAppData%\Programs\Inno Setup 6\ISCC.exe")]
    return next((c for c in cands if c and os.path.isfile(c)), "")


def tr(lang, text):
    if lang == "pt_BR":
        return text
    try:
        with open(os.path.join(ROOT, "scarlet", "locales", lang + ".json"), encoding="utf-8") as f:
            return json.load(f).get(text, text)
    except OSError:
        return text


def iss_text(app_dir, out_dir):
    langs = "\n".join(f'Name: "{code}"; MessagesFile: "{path}"' for code, path in INNO_LANGS.items())
    custom = "\n".join(f"{code}.{key}={tr(code, text)}".replace("\n", " ")
                       for code in INNO_LANGS for key, text in MESSAGES.items())
    inst = os.path.join(ROOT, "installer")
    return f"""; Gerado por tools/build_inno.py — não edite à mão.
#define AppName "{APP_NAME}"
#define AppExe "ScarletDM.exe"

[Setup]
AppId={{{{6F2B7C1E-5D3A-4B8E-9C21-5CA7D0E1F9A4}}
AppName={{#AppName}}
AppVersion={VERSION}
AppVerName={{#AppName}} {VERSION}
AppPublisher={APP_NAME}
AppCopyright=MIT License
VersionInfoVersion={VERSION}.0
VersionInfoDescription={{#AppName}} Setup
DefaultDirName={{autopf}}\\{{#AppName}}
DefaultGroupName={{#AppName}}
DisableProgramGroupPage=yes
DisableDirPage=auto
; só para o usuário atual, sem pedir administrador (/ALLUSERS na linha de comando instala para todos)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={out_dir}
OutputBaseFilename=ScarletDM-{VERSION}-Setup
SetupIconFile={os.path.join(ROOT, "assets", "app.ico")}
UninstallDisplayIcon={{app}}\\{{#AppExe}}
UninstallDisplayName={{#AppName}}
WizardStyle=modern dynamic
WizardImageFile={inst}\\wizard.bmp,{inst}\\wizard-250.bmp
WizardSmallImageFile={inst}\\wizard-small.bmp,{inst}\\wizard-small-250.bmp
WizardImageFileDynamicDark={inst}\\wizard.bmp,{inst}\\wizard-250.bmp
WizardSmallImageFileDynamicDark={inst}\\wizard-small.bmp,{inst}\\wizard-small-250.bmp
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
CloseApplications=yes
RestartApplications=no
ShowLanguageDialog=auto
UsePreviousLanguage=no

[Languages]
{langs}

[CustomMessages]
{custom}

[Tasks]
Name: "desktopicon"; Description: "{{cm:CreateDesktopIcon}}"; GroupDescription: "{{cm:AdditionalIcons}}"
Name: "autostart"; Description: "{{cm:AutoStart}}"; GroupDescription: "{{cm:Options}}:"; Flags: unchecked
Name: "magnet"; Description: "{{cm:Magnet}}"; GroupDescription: "{{cm:Options}}:"

[InstallDelete]
; atualização: tira bibliotecas da versão anterior antes de copiar as novas
Type: filesandordirs; Name: "{{app}}\\_internal"

[Files]
Source: "{app_dir}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{autoprograms}}\\{{#AppName}}"; Filename: "{{app}}\\{{#AppExe}}"
Name: "{{autodesktop}}\\{{#AppName}}"; Filename: "{{app}}\\{{#AppExe}}"; Tasks: desktopicon

[Run]
; grava idioma escolhido, "iniciar com o Windows" e associações usando o próprio app (mesma lógica das Preferências)
Filename: "{{app}}\\{{#AppExe}}"; Parameters: "--setup-done {{language}}"; Flags: runhidden waituntilterminated; Check: not IsUpdate; Tasks: not autostart and not magnet
Filename: "{{app}}\\{{#AppExe}}"; Parameters: "--setup-done {{language}} --autostart"; Flags: runhidden waituntilterminated; Check: not IsUpdate; Tasks: autostart and not magnet
Filename: "{{app}}\\{{#AppExe}}"; Parameters: "--setup-done {{language}} --handlers"; Flags: runhidden waituntilterminated; Check: not IsUpdate; Tasks: magnet and not autostart
Filename: "{{app}}\\{{#AppExe}}"; Parameters: "--setup-done {{language}} --autostart --handlers"; Flags: runhidden waituntilterminated; Check: not IsUpdate; Tasks: autostart and magnet
Filename: "{{app}}\\{{#AppExe}}"; Description: "{{cm:LaunchProgram,{{#AppName}}}}"; Flags: nowait postinstall skipifsilent
; atualização pelo próprio app (/UPDATE=1, silenciosa): não mexe nas preferências e reabre o Scarlet no fim
Filename: "{{app}}\\{{#AppExe}}"; Flags: nowait; Check: IsUpdate

[UninstallRun]
Filename: "{{app}}\\{{#AppExe}}"; Parameters: "--quit"; Flags: runhidden waituntilterminated; RunOnceId: "QuitScarlet"
Filename: "{{app}}\\{{#AppExe}}"; Parameters: "--unregister"; Flags: runhidden waituntilterminated; RunOnceId: "UnregScarlet"

[Code]
function IsUpdate: Boolean;
begin
  Result := ExpandConstant('{{param:UPDATE|0}}') = '1';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  // pede para o Scarlet aberto salvar e fechar antes de copiar os arquivos
  if FileExists(ExpandConstant('{{app}}\\{{#AppExe}}')) then
    Exec(ExpandConstant('{{app}}\\{{#AppExe}}'), '--quit', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
    if MsgBox(CustomMessage('RemoveData') + '?' + #13#10#13#10 + CustomMessage('KeepFiles'),
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{{userappdata}}\\ScarletDM'), True, True, True);
end;
"""


def main(app_dir, out_dir):
    iscc = find_iscc()
    if not iscc:
        print("Inno Setup 6 não encontrado (https://jrsoftware.org/isdl.php ou defina ISCC=caminho\\ISCC.exe)")
        return 1
    if not os.path.isfile(os.path.join(app_dir, "ScarletDM.exe")):
        print("Rode antes o build_exe.bat (não achei", os.path.join(app_dir, "ScarletDM.exe"), ")")
        return 1
    work = os.path.join(os.path.abspath(os.environ.get("SDM_BUILD") or os.path.join(ROOT, "build")), "inno")
    os.makedirs(work, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    iss = os.path.join(work, "ScarletDM.iss")
    with open(iss, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(iss_text(app_dir, out_dir))
    r = subprocess.run([iscc, "/Q", iss])
    exe = os.path.join(out_dir, f"ScarletDM-{VERSION}-Setup.exe")
    if r.returncode != 0 or not os.path.isfile(exe):
        print("FALHOU (veja", iss, ")")
        return 1
    print(f"ok: {exe} ({os.path.getsize(exe) / 1048576:.1f} MB)")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    sys.exit(main(os.path.abspath(a[0]) if a else os.path.join(ROOT, "dist", "ScarletDM"),
                  os.path.abspath(a[1]) if len(a) > 1 else os.path.join(ROOT, "release")))
