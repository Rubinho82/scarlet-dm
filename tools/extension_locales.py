"""Gera extension/_locales/<idioma>/messages.json (traduções da extensão do navegador).

Uso: python tools/extension_locales.py
Para mudar um texto ou adicionar um idioma, edite a tabela abaixo e rode de novo.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

IDS = ["extName", "extDesc", "menuLink", "menuMedia", "menuSelection", "menuPageMedia", "menuPage", "noFiles",
       "noFilesPage", "offline", "checking", "connected", "appClosed", "detected", "btnPageMedia", "btnPage",
       "btnShow", "prefs", "optIntercept", "optMinSize", "optSkipHtml", "optSkipDomains", "phSkipDomains",
       "optSkipExts", "optPort", "noMedia", "hlsStream", "download", "sent", "pageSent", "linksSent"]

T = {
    "pt_BR": [
        "Scarlet DM — Integração", "Envia downloads, links e vídeos (HLS) do navegador para o Scarlet DM.",
        "Baixar com Scarlet DM", "Baixar esta mídia com Scarlet DM", "Baixar os links selecionados",
        "Baixar o vídeo/música desta página (YouTube, SoundCloud…)", "Baixar todos os arquivos desta página",
        "Nenhum arquivo encontrado.", "Nenhum arquivo encontrado na página.",
        "O Scarlet DM não está aberto (ou a integração com o navegador está desligada nas Preferências).",
        "verificando…", "conectado", "app fechado", "Mídias detectadas nesta aba",
        "Baixar o vídeo/música desta página", "Baixar arquivos da página", "Abrir o Scarlet DM", "Preferências",
        "Capturar downloads do navegador", "Ignorar arquivos menores que (KB)", "Não capturar páginas da web",
        "Pular estes sites (ex.: drive.google.com, mega.nz)", "um por linha ou separados por vírgula",
        "Pular estas extensões (ex.: pdf, jpg)", "Porta do app",
        "Nenhum vídeo ou áudio detectado. Dê play no vídeo e abra de novo.", "stream HLS", "Baixar",
        "Enviado para o Scarlet DM.", "Página enviada: escolha a qualidade no Scarlet DM.", "$1 link(s) enviado(s)."],
    "en": [
        "Scarlet DM — Integration", "Sends downloads, links and videos (HLS) from the browser to Scarlet DM.",
        "Download with Scarlet DM", "Download this media with Scarlet DM", "Download the selected links",
        "Download this page's video/music (YouTube, SoundCloud…)", "Download all files on this page",
        "No files found.", "No files found on the page.",
        "Scarlet DM is not open (or browser integration is turned off in Preferences).",
        "checking…", "connected", "app closed", "Media detected in this tab",
        "Download this page's video/music", "Download page files", "Open Scarlet DM", "Preferences",
        "Capture browser downloads", "Ignore files smaller than (KB)", "Don't capture web pages",
        "Skip these sites (e.g. drive.google.com, mega.nz)", "one per line or comma-separated",
        "Skip these extensions (e.g. pdf, jpg)", "App port",
        "No video or audio detected. Play the video and open this again.", "HLS stream", "Download",
        "Sent to Scarlet DM.", "Page sent: choose the quality in Scarlet DM.", "$1 link(s) sent."],
    "es": [
        "Scarlet DM — Integración", "Envía descargas, enlaces y vídeos (HLS) del navegador a Scarlet DM.",
        "Descargar con Scarlet DM", "Descargar este medio con Scarlet DM", "Descargar los enlaces seleccionados",
        "Descargar el vídeo/música de esta página (YouTube, SoundCloud…)", "Descargar todos los archivos de esta página",
        "No se encontraron archivos.", "No se encontraron archivos en la página.",
        "Scarlet DM no está abierto (o la integración con el navegador está desactivada en Preferencias).",
        "comprobando…", "conectado", "app cerrada", "Medios detectados en esta pestaña",
        "Descargar el vídeo/música de esta página", "Descargar archivos de la página", "Abrir Scarlet DM", "Preferencias",
        "Capturar las descargas del navegador", "Ignorar archivos menores de (KB)", "No capturar páginas web",
        "Omitir estos sitios (ej.: drive.google.com, mega.nz)", "uno por línea o separados por comas",
        "Omitir estas extensiones (ej.: pdf, jpg)", "Puerto de la app",
        "No se detectó vídeo ni audio. Reproduce el vídeo y vuelve a abrir esto.", "stream HLS", "Descargar",
        "Enviado a Scarlet DM.", "Página enviada: elige la calidad en Scarlet DM.", "$1 enlace(s) enviado(s)."],
    "fr": [
        "Scarlet DM — Intégration", "Envoie les téléchargements, liens et vidéos (HLS) du navigateur vers Scarlet DM.",
        "Télécharger avec Scarlet DM", "Télécharger ce média avec Scarlet DM", "Télécharger les liens sélectionnés",
        "Télécharger la vidéo/musique de cette page (YouTube, SoundCloud…)", "Télécharger tous les fichiers de cette page",
        "Aucun fichier trouvé.", "Aucun fichier trouvé sur la page.",
        "Scarlet DM n'est pas ouvert (ou l'intégration au navigateur est désactivée dans les Préférences).",
        "vérification…", "connecté", "app fermée", "Médias détectés dans cet onglet",
        "Télécharger la vidéo/musique de cette page", "Télécharger les fichiers de la page", "Ouvrir Scarlet DM",
        "Préférences", "Capturer les téléchargements du navigateur", "Ignorer les fichiers de moins de (Ko)",
        "Ne pas capturer les pages web", "Ignorer ces sites (ex. : drive.google.com, mega.nz)",
        "un par ligne ou séparés par des virgules", "Ignorer ces extensions (ex. : pdf, jpg)", "Port de l'app",
        "Aucune vidéo ni aucun audio détecté. Lancez la vidéo et rouvrez ceci.", "flux HLS", "Télécharger",
        "Envoyé à Scarlet DM.", "Page envoyée : choisissez la qualité dans Scarlet DM.", "$1 lien(s) envoyé(s)."],
    "de": [
        "Scarlet DM — Integration", "Sendet Downloads, Links und Videos (HLS) aus dem Browser an Scarlet DM.",
        "Mit Scarlet DM herunterladen", "Dieses Medium mit Scarlet DM herunterladen", "Ausgewählte Links herunterladen",
        "Video/Musik dieser Seite herunterladen (YouTube, SoundCloud…)", "Alle Dateien dieser Seite herunterladen",
        "Keine Dateien gefunden.", "Keine Dateien auf der Seite gefunden.",
        "Scarlet DM ist nicht geöffnet (oder die Browser-Integration ist in den Einstellungen aus).",
        "wird geprüft…", "verbunden", "App geschlossen", "In diesem Tab erkannte Medien",
        "Video/Musik dieser Seite herunterladen", "Dateien der Seite herunterladen", "Scarlet DM öffnen",
        "Einstellungen", "Browser-Downloads abfangen", "Dateien kleiner als (KB) ignorieren",
        "Keine Webseiten abfangen", "Diese Seiten überspringen (z. B. drive.google.com, mega.nz)",
        "eine pro Zeile oder durch Kommas getrennt", "Diese Endungen überspringen (z. B. pdf, jpg)", "App-Port",
        "Kein Video oder Audio erkannt. Starten Sie das Video und öffnen Sie dies erneut.", "HLS-Stream",
        "Herunterladen", "An Scarlet DM gesendet.", "Seite gesendet: Wählen Sie die Qualität in Scarlet DM.",
        "$1 Link(s) gesendet."],
    "it": [
        "Scarlet DM — Integrazione", "Invia download, link e video (HLS) dal browser a Scarlet DM.",
        "Scarica con Scarlet DM", "Scarica questo media con Scarlet DM", "Scarica i link selezionati",
        "Scarica il video/musica di questa pagina (YouTube, SoundCloud…)", "Scarica tutti i file di questa pagina",
        "Nessun file trovato.", "Nessun file trovato nella pagina.",
        "Scarlet DM non è aperto (o l'integrazione con il browser è disattivata nelle Preferenze).",
        "verifica…", "connesso", "app chiusa", "Media rilevati in questa scheda",
        "Scarica il video/musica di questa pagina", "Scarica i file della pagina", "Apri Scarlet DM", "Preferenze",
        "Cattura i download del browser", "Ignora i file più piccoli di (KB)", "Non catturare pagine web",
        "Salta questi siti (es.: drive.google.com, mega.nz)", "uno per riga o separati da virgole",
        "Salta queste estensioni (es.: pdf, jpg)", "Porta dell'app",
        "Nessun video o audio rilevato. Avvia il video e riapri questo pannello.", "flusso HLS", "Scarica",
        "Inviato a Scarlet DM.", "Pagina inviata: scegli la qualità in Scarlet DM.", "$1 link inviati."],
    "ru": [
        "Scarlet DM — Интеграция", "Передаёт загрузки, ссылки и видео (HLS) из браузера в Scarlet DM.",
        "Скачать через Scarlet DM", "Скачать этот медиафайл через Scarlet DM", "Скачать выделенные ссылки",
        "Скачать видео/музыку с этой страницы (YouTube, SoundCloud…)", "Скачать все файлы с этой страницы",
        "Файлы не найдены.", "На странице не найдено файлов.",
        "Scarlet DM не открыт (или интеграция с браузером выключена в Настройках).",
        "проверка…", "подключено", "приложение закрыто", "Медиа, найденные на этой вкладке",
        "Скачать видео/музыку с этой страницы", "Скачать файлы страницы", "Открыть Scarlet DM", "Настройки",
        "Перехватывать загрузки браузера", "Пропускать файлы меньше (КБ)", "Не перехватывать веб-страницы",
        "Пропускать эти сайты (напр.: drive.google.com, mega.nz)", "по одному в строке или через запятую",
        "Пропускать эти расширения (напр.: pdf, jpg)", "Порт приложения",
        "Видео или аудио не найдено. Запустите видео и откройте это окно снова.", "поток HLS", "Скачать",
        "Отправлено в Scarlet DM.", "Страница отправлена: выберите качество в Scarlet DM.", "Отправлено ссылок: $1."],
    "tr": [
        "Scarlet DM — Entegrasyon", "Tarayıcıdaki indirmeleri, bağlantıları ve videoları (HLS) Scarlet DM'e gönderir.",
        "Scarlet DM ile indir", "Bu medyayı Scarlet DM ile indir", "Seçili bağlantıları indir",
        "Bu sayfanın videosunu/müziğini indir (YouTube, SoundCloud…)", "Bu sayfadaki tüm dosyaları indir",
        "Dosya bulunamadı.", "Sayfada dosya bulunamadı.",
        "Scarlet DM açık değil (veya tarayıcı entegrasyonu Tercihler'de kapalı).",
        "denetleniyor…", "bağlı", "uygulama kapalı", "Bu sekmede bulunan medyalar",
        "Bu sayfanın videosunu/müziğini indir", "Sayfadaki dosyaları indir", "Scarlet DM'i aç", "Tercihler",
        "Tarayıcı indirmelerini yakala", "Şundan küçük dosyaları yok say (KB)", "Web sayfalarını yakalama",
        "Bu siteleri atla (ör.: drive.google.com, mega.nz)", "her satıra bir tane veya virgülle ayrılmış",
        "Bu uzantıları atla (ör.: pdf, jpg)", "Uygulama portu",
        "Video veya ses bulunamadı. Videoyu oynatıp bunu yeniden açın.", "HLS akışı", "İndir",
        "Scarlet DM'e gönderildi.", "Sayfa gönderildi: kaliteyi Scarlet DM'de seçin.", "$1 bağlantı gönderildi."],
    "zh_CN": [
        "Scarlet DM — 浏览器集成", "把浏览器中的下载、链接和视频（HLS）发送到 Scarlet DM。",
        "使用 Scarlet DM 下载", "使用 Scarlet DM 下载此媒体", "下载选中的链接",
        "下载此页面的视频/音乐（YouTube、SoundCloud…）", "下载此页面上的所有文件",
        "未找到文件。", "页面上未找到文件。",
        "Scarlet DM 未打开（或在首选项中关闭了浏览器集成）。",
        "正在检查…", "已连接", "应用已关闭", "此标签页中检测到的媒体",
        "下载此页面的视频/音乐", "下载页面文件", "打开 Scarlet DM", "首选项",
        "接管浏览器下载", "忽略小于此大小的文件（KB）", "不接管网页",
        "跳过这些网站（例如 drive.google.com、mega.nz）", "每行一个或用逗号分隔",
        "跳过这些扩展名（例如 pdf、jpg）", "应用端口",
        "未检测到视频或音频。请先播放视频再打开这里。", "HLS 流", "下载",
        "已发送到 Scarlet DM。", "页面已发送：请在 Scarlet DM 中选择质量。", "已发送 $1 个链接。"],
    "ja": [
        "Scarlet DM — 連携", "ブラウザーのダウンロード、リンク、動画（HLS）を Scarlet DM に送ります。",
        "Scarlet DM でダウンロード", "このメディアを Scarlet DM でダウンロード", "選択したリンクをダウンロード",
        "このページの動画/音楽をダウンロード（YouTube、SoundCloud…）", "このページのファイルをすべてダウンロード",
        "ファイルが見つかりません。", "ページにファイルが見つかりません。",
        "Scarlet DM が起動していません（または設定でブラウザー連携がオフです）。",
        "確認中…", "接続済み", "アプリ終了中", "このタブで検出したメディア",
        "このページの動画/音楽をダウンロード", "ページのファイルをダウンロード", "Scarlet DM を開く", "設定",
        "ブラウザーのダウンロードを横取りする", "これより小さいファイルは無視（KB）", "ウェブページは横取りしない",
        "これらのサイトはスキップ（例：drive.google.com、mega.nz）", "1 行に 1 つ、またはカンマ区切り",
        "これらの拡張子はスキップ（例：pdf、jpg）", "アプリのポート",
        "動画や音声が見つかりません。動画を再生してから開き直してください。", "HLS ストリーム", "ダウンロード",
        "Scarlet DM に送信しました。", "ページを送信しました：Scarlet DM で品質を選んでください。",
        "$1 件のリンクを送信しました。"],
    "ko": [
        "Scarlet DM — 연동", "브라우저의 다운로드, 링크, 동영상(HLS)을 Scarlet DM으로 보냅니다.",
        "Scarlet DM으로 다운로드", "이 미디어를 Scarlet DM으로 다운로드", "선택한 링크 다운로드",
        "이 페이지의 동영상/음악 다운로드(YouTube, SoundCloud…)", "이 페이지의 모든 파일 다운로드",
        "파일을 찾지 못했습니다.", "페이지에서 파일을 찾지 못했습니다.",
        "Scarlet DM이 열려 있지 않습니다(또는 환경설정에서 브라우저 연동이 꺼져 있습니다).",
        "확인 중…", "연결됨", "앱 닫힘", "이 탭에서 감지된 미디어",
        "이 페이지의 동영상/음악 다운로드", "페이지 파일 다운로드", "Scarlet DM 열기", "환경설정",
        "브라우저 다운로드 가로채기", "이보다 작은 파일 무시(KB)", "웹 페이지는 가로채지 않기",
        "이 사이트 건너뛰기(예: drive.google.com, mega.nz)", "한 줄에 하나 또는 쉼표로 구분",
        "이 확장자 건너뛰기(예: pdf, jpg)", "앱 포트",
        "동영상이나 오디오가 감지되지 않았습니다. 동영상을 재생한 뒤 다시 여세요.", "HLS 스트림", "다운로드",
        "Scarlet DM으로 보냈습니다.", "페이지를 보냈습니다: Scarlet DM에서 품질을 고르세요.", "링크 $1개를 보냈습니다."],
}


def main():
    for lang, texts in T.items():
        assert len(texts) == len(IDS), (lang, len(texts))
        d = os.path.join(ROOT, "extension", "_locales", lang)
        os.makedirs(d, exist_ok=True)
        msgs = {}
        for k, v in zip(IDS, texts):
            msgs[k] = {"message": v}
            if "$1" in v:
                msgs[k]["message"] = v.replace("$1", "$COUNT$")
                msgs[k]["placeholders"] = {"count": {"content": "$1"}}
        if lang == "en":
            msgs["extName"]["description"] = "Extension name (max 45 chars)"
        with open(os.path.join(d, "messages.json"), "w", encoding="utf-8") as f:
            json.dump(msgs, f, ensure_ascii=False, indent=1)
        assert len(msgs["extName"]["message"]) <= 45
    print(len(T), "idiomas ->", os.path.join(ROOT, "extension", "_locales"))


if __name__ == "__main__":
    main()
