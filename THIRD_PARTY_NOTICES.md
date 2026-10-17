# Third-party software / Componentes de terceiros

Scarlet DM is MIT-licensed (see `LICENSE`). The Windows build bundles or downloads the components below,
each under its own license. / O Scarlet DM é MIT; o executável inclui ou baixa os componentes abaixo,
cada um com a sua licença.

## Bundled with the program / Incluídos no programa

| Component | License | Source |
|---|---|---|
| Qt 6 and PySide6 (Qt for Python) | LGPL-3.0 | https://www.qt.io/download-open-source · https://code.qt.io |
| FFmpeg libraries used by Qt Multimedia (avcodec, avformat, avutil, swscale, swresample) | LGPL-2.1+ | https://ffmpeg.org |
| Python 3.10 runtime | PSF License | https://www.python.org |
| requests | Apache-2.0 | https://github.com/psf/requests |
| urllib3 | MIT | https://github.com/urllib3/urllib3 |
| certifi | MPL-2.0 | https://github.com/certifi/python-certifi |
| charset-normalizer | MIT | https://github.com/jawah/charset_normalizer |
| idna | BSD-3-Clause | https://github.com/kjd/idna |
| cryptography | Apache-2.0 or BSD-3-Clause | https://github.com/pyca/cryptography |
| OpenSSL | Apache-2.0 | https://www.openssl.org |
| libtorrent (Rasterbar) | BSD-3-Clause | https://github.com/arvidn/libtorrent |
| Boost | BSL-1.0 | https://www.boost.org |
| Brotli | MIT | https://github.com/google/brotli |
| PyInstaller bootloader | GPL-2.0+ with bootloader exception (allows any license for the bundled app) | https://pyinstaller.org |

**LGPL note (Qt/PySide6/FFmpeg):** these libraries are shipped as separate, unmodified DLLs inside the
`_internal` folder and are loaded dynamically. You may replace them with your own compatible builds.
Their source code is available at the links above. / As bibliotecas LGPL ficam como DLLs separadas e sem
modificação na pasta `_internal` e podem ser trocadas por outras versões compatíveis.

## Downloaded on demand / Baixados quando necessário

These are **not** shipped with Scarlet DM. They are downloaded from their official releases the first time
a site video/music is downloaded, into `%APPDATA%\ScarletDM\bin`. / Não vêm junto: são baixados das
fontes oficiais na primeira vez que um vídeo/música de site é baixado.

| Component | License | Source |
|---|---|---|
| yt-dlp | Unlicense | https://github.com/yt-dlp/yt-dlp |
| FFmpeg / FFprobe (yt-dlp/FFmpeg-Builds) | GPL-3.0 | https://github.com/yt-dlp/FFmpeg-Builds |
| Deno (JavaScript runtime used for YouTube) | MIT | https://github.com/denoland/deno |

## Browser extension / Extensão do navegador

The extension (`extension/`) contains only Scarlet DM code (MIT). / A extensão só tem código do Scarlet DM (MIT).
