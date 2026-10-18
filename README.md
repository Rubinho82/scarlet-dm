# Scarlet DM

**Site e downloads:** https://rubinho82.github.io/scarlet-dm/ · [Releases](https://github.com/Rubinho82/scarlet-dm/releases/latest)

Gerenciador de downloads para Windows com tema vermelho e preto, inspirado no Free Download Manager
(a lógica de seções foi tirada da engenharia reversa do `downloadswww.dll` do FDM) e com recursos a mais.
Licença MIT (veja `LICENSE` e `THIRD_PARTY_NOTICES.md`). 11 idiomas. **Windows, macOS e Linux.**

## Para quem vai usar

- **Windows — instalador:** `ScarletDM-2.0.0-Setup.exe` (Inno Setup) — instala só para o usuário (sem pedir
  administrador), pergunta idioma, cria atalhos (Área de Trabalho e Menu Iniciar), pergunta se deve iniciar com o
  Windows e se abre links magnet/.torrent. Desinstala por Configurações › Aplicativos (pergunta se apaga os dados).
- **macOS:** `ScarletDM-2.0.0-macos-arm64.dmg` (Apple Silicon) / `-macos-x64.dmg` (Intel) — arraste para Aplicativos.
  Na primeira vez: botão direito → Abrir (sem a conta paga de desenvolvedor da Apple não há notarização).
- **Linux:** `ScarletDM-2.0.0-linux-x64.AppImage` (um arquivo, qualquer distro de 2022 para cá; `chmod +x` e rode) ou
  `.tar.gz`. Dados em `~/.local/share/ScarletDM`, iniciar com o sistema em `~/.config/autostart`, links magnet via
  `xdg-mime`.
  O Windows não deixa programas se fixarem sozinhos na barra de tarefas; o instalador ensina o clique direito → Fixar.
- **Portátil:** `ScarletDM-2.0.0-Portable.zip` — descompacte e rode. Com o `portable.ini` ao lado do `.exe`, lista e
  configurações ficam em `data\` na própria pasta (bom para pendrive). Na primeira abertura aparece uma tela de
  boas-vindas (idioma, pasta, iniciar com o Windows, atalho).
- Vídeos e músicas de sites: nada para instalar. Na primeira vez o app baixa sozinho, das fontes oficiais, o
  `yt-dlp.exe`, o ffmpeg e o Deno (usado pelo YouTube) para `%APPDATA%\ScarletDM\bin` e os mantém atualizados.

## Para desenvolver

```bat
pip install -r requirements.txt
run.bat
```

`criar_atalho.bat` cria atalhos para rodar pelo código-fonte.

## Gerar o .exe e os pacotes

```bat
build_exe.bat            :: dist\ScarletDM\ScarletDM.exe (pasta portátil)
build_exe.bat release    :: + release\ com tudo para publicar
```

No Linux/macOS: `bash tools/build_unix.sh` (AppImage + .tar.gz / .app + .dmg, já com autoteste).
**Os três sistemas de uma vez:** suba o código para o GitHub — `.github/workflows/build.yml` compila e testa em
Windows, Linux e macOS (Intel e Apple Silicon); criar uma tag `v2.0.0` publica um Release com todos os arquivos.

`release\` recebe: `ScarletDM-<v>-Setup.exe` (Inno Setup), `ScarletDM-<v>-Portable.zip`,
`ScarletDM-<v>-source.zip` (edição open source), `scarlet-dm-chromium.zip` e `scarlet-dm-firefox.zip` (para as lojas
de extensões) e `SHA256SUMS.txt`.

- O build tira do pacote as partes do Qt que o app não usa (`tools\trim_dist.py`, ~45 MB a menos).
- Disco cheio? Gere em outro disco: `set SDM_DIST=F:\sdm\dist`, `set SDM_BUILD=F:\sdm\work`,
  `set SDM_RELEASE=F:\sdm\release` antes do `build_exe.bat`.
- Para testar o `.exe` gerado: `ScarletDM.exe --selftest [um_video.mp4] --out resultado.json` (bibliotecas,
  traduções, janela e player; código de saída 0 = tudo ok).
- O instalador é gerado por `toolsuild_inno.py` com o [Inno Setup 6](https://jrsoftware.org/isdl.php)
  (o mesmo instalador do VS Code, Git e Python): antivírus o conhecem, ao contrário de um "Setup.exe" feito com
  PyInstaller. Os textos do instalador vêm das traduções do app.

**Antivírus e avisos do sistema (para publicar para muita gente):**
- Use um PyInstaller com bootloader compilado na sua máquina (`set PYINSTALLER_COMPILE_BOOTLOADER=1` +
  `pip install --no-binary pyinstaller pyinstaller` num venv; aponte `SDM_PY` para ele). Os antivírus marcam o
  bootloader padrão porque malware também o usa; o compilado por você é único. O workflow do GitHub já faz isso.
- O `Setup.exe` é Inno Setup e o app é uma pasta normal (não "um .exe que se extrai sozinho"), o formato menos acusado.
- O que zera os avisos de vez é **assinatura digital**: certificado de code signing (ou grátis para open source pela
  SignPath Foundation; Azure Trusted Signing é barato). Sem isso, o SmartScreen avisa nas primeiras semanas
  (“Mais informações → Executar assim mesmo”) até o arquivo ganhar reputação.
- Se algum antivírus acusar: envie o arquivo como falso positivo (Microsoft: microsoft.com/wdsi/filesubmission).
- macOS: sem conta Apple Developer (US$ 99/ano) o app sai só com assinatura ad hoc; com ela dá para notarizar.

## O que ele faz

| Recurso | Scarlet DM | FDM |
|---|---|---|
| Várias conexões por arquivo (até 32), dividindo a maior parte restante ao meio | ✓ | ✓ |
| Retomar depois de pausar, fechar o app ou cair a internet | ✓ (estado salvo a cada 3 s e a cada mudança) | ✓ |
| Arquivo esparso (sem pré-alocar gigabytes de zeros) | ✓ | pré-aloca |
| Recuo automático quando o servidor reclama (HTTP 429/503 + `Retry-After`) | ✓ | — |
| `If-Range`: detecta arquivo trocado no servidor e recomeça sozinho | ✓ | — |
| Checksum MD5/SHA-1/SHA-256/SHA-512 automático ao terminar | ✓ | — |
| **Mapa de seções ao vivo** (onde cada conexão está) | ✓ | — |
| **Gráfico de velocidade** por download e total | ✓ | — |
| **Player embutido** (tela cheia, clicar na barra para pular, prévia do tempo, atalhos) | ✓ | ✓ |
| Painel de detalhes com miniatura, resolução, fps, codecs, duração | ✓ | ✓ |
| Compactar vários em ZIP, mover para pasta, extrair aqui | ✓ | parcial |
| Streams HLS `.m3u8`: melhor qualidade, áudio separado, AES-128 → `.mp4` | ✓ | ✓ |
| Torrents e links magnet (escolher arquivos, retomar, semear opcional) | ✓ (libtorrent) | ✓ |
| Fila com limite de downloads simultâneos, mover para topo/fim | ✓ | parcial |
| Limite de velocidade global com um clique + predefinições | ✓ | ✓ |
| Agendador diário (retomar/pausar em horários) | ✓ | — |
| Desligar o PC quando tudo terminar (com contagem regressiva) | ✓ | ✓ |
| Monitor da área de transferência | ✓ | ✓ |
| Arrastar links, `.txt` ou `.torrent` para a janela | ✓ | ✓ |
| “Alterar link” quando o link expira, mantendo o progresso | ✓ | — |
| Filtros (ativos, concluídos, com erro, arquivos ausentes, por tipo) + busca | ✓ | ✓ |
| Extensão: Chrome, Edge, Brave, Opera, Vivaldi **e Firefox** — captura downloads, menu de contexto, links da página, detecção de vídeos | ✓ | ✓ |
| **Vídeos e músicas de sites** (YouTube, SoundCloud, Vimeo, X, Instagram, TikTok, Twitch… +1000): resolução até 4K, **30 ou 60 fps**, só áudio MP3 (**320/256/192/128 kbps**), M4A, OPUS ou FLAC, com capa, playlists | ✓ (componentes baixados e atualizados sozinhos) | ✓ |
| Download em lote por padrão (`foto[001-100].jpg`, `[a-z]`) | ✓ | — |
| Limite de conexões por servidor e total | ✓ | ✓ |
| Verificar com antivírus ao concluir (Windows Defender detectado sozinho) | ✓ | manual |
| Marcar arquivos baixados (Zone.Identifier) e usar a data do servidor | ✓ | ✓ |
| Repetir automaticamente downloads que caíram por erro de rede | ✓ | ✓ |
| Remover da lista concluídos / arquivos apagados, backup automático da lista | ✓ | ✓ |
| Executar um programa ao concluir (`%path%`) | ✓ | ✓ |
| Impedir suspensão do PC enquanto baixa | ✓ | ✓ |
| Torrent: criptografia, DHT/LSD/UPnP/uTP, parar na proporção, pasta monitorada, app padrão para magnet | ✓ | ✓ |
| **Acesso remoto** pelo celular (página web na rede local, com senha — sem nuvem de terceiros) | ✓ | ✓ (via nuvem) |
| Notificações configuráveis (concluído, adicionado, falha, só com janela inativa, som) | ✓ | ✓ |
| 11 idiomas (pt-BR, en, es, fr, de, it, ru, tr, zh-CN, ja, ko) no app, no instalador e na extensão | ✓ | ✓ |
| Leve: ~0,3% de CPU parado, ~5 MB de RAM minimizado na bandeja | ✓ | — |
| Velocidade medida: 82,8 MB/s com 8 conexões (curl com 8 conexões: 80,2 MB/s) | ✓ | — |

## Atalhos

| Tecla | Ação |
|---|---|
| Ctrl+N | Adicionar download |
| Ctrl+V (na lista) | Colar links da área de transferência |
| Espaço | Pausar / retomar o selecionado |
| Enter / duplo clique | Abrir o arquivo concluído (vídeo/música abre no player) |
| Del | Excluir (pergunta se apaga o arquivo também) |
| Ctrl+Shift+C | Copiar link |
| Ctrl+F | Pesquisar |
| Ctrl+O | Abrir `.torrent` |
| Ctrl+, | Preferências |
| Ctrl+Q | Sair de vez (fechar a janela só esconde na bandeja) |

No player: Espaço/K tocar-pausar, F/F11 ou duplo clique tela cheia, Esc sai da tela cheia, ←/→ 5 s, J/L 10 s,
↑/↓ volume, M mudo, N/P próximo/anterior.

## Extensão do navegador

- **Chrome, Edge, Brave, Opera, Vivaldi:** página de extensões (`chrome://extensions`, `edge://extensions`…) →
  **Modo do desenvolvedor** → **Carregar sem compactação** → pasta `extension\` (ao lado do `ScarletDM.exe`).
- **Firefox:** `about:debugging` → **Este Firefox** → **Carregar extensão temporária** → `manifest.json` da pasta
  `extension-firefox\` (dura até fechar o Firefox). Para ficar permanente, publique `scarlet-dm-firefox.zip` no
  addons.mozilla.org (pode ser “não listado”: a Mozilla assina e você distribui o `.xpi` no seu site).
- **Lojas:** `scarlet-dm-chromium.zip` serve para a Chrome Web Store, Edge Add-ons e Opera Add-ons — publicada, a
  extensão instala com um clique.
- **Qualquer outro navegador:** deixe ligado “Monitorar a área de transferência” — copie o link e o Scarlet oferece.

Com o app aberto, os downloads do navegador vão para o Scarlet DM (com cookies, referer e o User-Agent do navegador,
para links que exigem login). Com o app fechado, o navegador baixa normalmente. O ícone da extensão mostra quantos
vídeos/áudios foram detectados na aba e baixa qualquer um com um clique.

A comunicação é só local (`127.0.0.1:47331`, porta exclusiva). O app só aceita pedidos de extensões e com um cabeçalho
próprio, então páginas da web não conseguem colocar downloads na sua fila.

## Linha de comando

```bat
ScarletDM.exe https://site/arquivo.zip     :: abre (ou usa a janela já aberta) com o link
ScarletDM.exe C:\caminho\filme.torrent
ScarletDM.exe --tray                       :: inicia minimizado
ScarletDM.exe --quit                       :: fecha a instância aberta (salva tudo antes)
ScarletDM.exe --selftest [video] [--out x.json]
ScarletDM.exe --uninstall [--silent [--remove-data]]

ScarletDM-2.0.0-Setup.exe --silent [--dir PASTA] [--no-desktop] [--no-startmenu] [--autostart]
                          [--no-handlers] [--no-launch] [--lang en]
```

Pelo código-fonte é igual, trocando `ScarletDM.exe` por `python main.py`.

## Onde ficam os dados

`%APPDATA%\ScarletDM\` (ou `data\` ao lado do `.exe` no modo portátil) — `downloads.json` (lista e progresso),
`settings.json`, `torrents\` (retomada de torrents), `bin\` (componentes de vídeo), `thumbs\` (miniaturas).
Downloads incompletos ficam ao lado do destino como `nome.ext.sdm` (HTTP) ou `.nome.sdm-hls\` (streams).

## Traduções

Os textos do código são as chaves (em português) e passam por `_()` (`scarlet/i18n.py`).

```bat
python tools\extract_strings.py   :: lista as frases do código (não precisa rodar para traduzir)
python tools\check_locales.py ja  :: o que falta traduzir em um idioma
python tools\build_locales.py     :: tools\translations\*.tsv -> scarlet\locales\*.json (confere os {marcadores})
python tools\extension_locales.py :: traduções da extensão (extension\_locales)
```

Nos `.tsv`, linhas `número<TAB>tradução` seguem a numeração original e linhas `=texto original<TAB>tradução` servem
para frases novas. Para um idioma novo: copie `en.tsv`, traduza, acrescente o código em `LANGUAGES` (`scarlet/i18n.py`)
e na tabela de `tools/extension_locales.py`.

## Limitações conhecidas

- Não baixa conteúdo com DRM (Spotify, Netflix, Deezer, Apple Music; SAMPLE-AES/Widevine) nem transmissões HLS ao vivo.
- Vídeos de sites dependem do yt-dlp estar atualizado (o app atualiza toda semana; dá para forçar em
  Preferências › Vídeos de sites).
- Downloads do navegador que dependem de formulário POST podem falhar ao serem capturados; desligue a captura no
  popup da extensão para esses sites.
- Sem assinatura digital, o SmartScreen avisa nas primeiras semanas (veja “Antivírus e avisos do sistema”).
- Linux: o ícone de bandeja depende do ambiente (no GNOME precisa da extensão AppIndicator); sem bandeja, fechar a
  janela fecha o app.

## Estrutura

```
main.py                   entrada, instância única, linha de comando, --selftest/--uninstall/--quit
scarlet/engine/           motor: http_task (seções), hls_task, media_task (vídeos de sites), components, torrent,
                          manager, ratelimit
scarlet/ui/               interface PySide6: janela, tabela, detalhes, player, diálogos, tema, boas-vindas,
                          telas do instalador (setup_ui)
scarlet/i18n.py           traduções; scarlet/locales/*.json
scarlet/install.py        atalhos, registro em Aplicativos instalados, desinstalação
scarlet/api.py            servidor local para a extensão
scarlet/remote.py         acesso remoto (página web com senha)
scarlet/selftest.py       autoteste do .exe
installer/                arte e idioma chinês do instalador Inno Setup (+ setup.py: instalador próprio antigo)
packaging/scarlet_unix.spec  build do Linux/macOS (.github/workflows/build.yml roda nos três sistemas)
tests/                    testes do motor (HTTP segmentado, HLS, API da extensão)
extension/                extensão Manifest V3 (Chromium; a variante do Firefox é gerada no build)
site/                     página de download (index.html) — suba junto com os arquivos de release\ em downloads/
tools/                    build, release, ícones, traduções
```
