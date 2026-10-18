import json
import os

from . import API_PORT
from .util import app_data_dir, default_download_dir, DEFAULT_UA

DEFAULTS = {
    "download_dir": "",
    "category_subfolders": False,
    "max_active": 3,
    "connections": 8,
    "limit_enabled": False,
    "speed_limit": 2 * 1024 * 1024,
    "upload_limit": 0,
    "retries": 10,
    "timeout": 30,
    "user_agent": DEFAULT_UA,
    "proxy_mode": "none",          # none | system | manual
    "proxy_url": "",
    "verify_ssl": True,
    "clipboard_monitor": True,
    "minimize_to_tray": True,
    "close_to_tray": True,
    "notify_complete": True,
    "confirm_browser_links": True,
    "api_enabled": True,
    "api_port": API_PORT,
    "torrent_port": 6881,
    "torrent_seed": False,
    "ffmpeg_path": "",
    "hls_quality": "best",
    "scheduler_enabled": False,
    "scheduler_start": "02:00",
    "scheduler_stop": "07:00",
    # conexões
    "max_per_server": 16,
    "max_total_conns": 96,
    "skip_html": True,
    # depois de concluir
    "mark_downloaded": True,
    "use_server_time": False,
    "av_scan": False,
    "av_path": "",
    "av_args": "",
    "post_cmd_enabled": False,
    "post_cmd": "",
    "post_cmd_args": '"%path%"',
    # lista
    "auto_retry": True,
    "autoremove_missing": True,
    "autoremove_completed": False,
    "backup_hours": 3,
    "on_exists": "rename",          # rename | overwrite
    "delete_action": "ask",         # ask | list | files
    # notificações / energia / aparência
    "notify_added": False,
    "notify_errors": True,
    "notify_only_inactive": False,
    "notify_sound": False,
    "prevent_sleep": True,
    "compact": False,
    "language": "",
    "welcome_done": False,         # tela de boas-vindas da 1ª abertura (o instalador já marca como feita)
    "use_player": True,
    "ui_scale": 100,
    # torrent
    "torrent_ratio": 1.0,
    "torrent_dht": True,
    "torrent_lsd": True,
    "torrent_upnp": True,
    "torrent_utp": True,
    "torrent_encryption": "prefer",  # prefer | force | off
    "torrent_watch_dir": "",
    "torrent_watch_auto": False,
    "torrent_delete_source": False,
    # vídeos de sites (yt-dlp)
    "media_quality": "best",
    "media_fps": "",
    "media_audio_format": "mp3",
    "media_audio_kbps": "320",
    "media_container": "mp4",
    "media_compat": True,
    "media_subs": False,
    "ytdlp_auto_update": True,
    "ytdlp_last_update": 0,
    "check_updates": True,         # procura versão nova do Scarlet DM (1x por dia, no GitHub)
    "update_last_check": 0,
    "update_skip": "",             # versão que a pessoa mandou pular
    # acesso remoto
    "remote_enabled": False,
    "remote_port": 47332,
    "remote_password": "",
    "accent": "#e3222f",
    "window_geometry": "",
    "window_state": "",
    "splitter_state": "",
    "header_state": "",
    "details_visible": True,
    "filter": "all",
}


class Settings(dict):
    def __init__(self, path=None):
        super().__init__(DEFAULTS)
        self.path = path or os.path.join(app_data_dir(), "settings.json")
        self.load()
        if not self.get("download_dir"):
            self["download_dir"] = default_download_dir()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.update({k: v for k, v in data.items() if k in DEFAULTS})
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            pass

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dict(self), f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
