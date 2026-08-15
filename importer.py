"""Download audio from supported social URLs via yt-dlp (optional Geonode proxy)."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

import yt_dlp

from geonode_config import geonode_allow_direct, geonode_max_attempts, geonode_proxy_url
from page_parser import detect_platform
from proxy_config import (
    get_manual_proxy,
    get_proxy_url,
    manual_proxy_configured,
    mask_proxy,
    max_attempts,
    report_proxy_failure,
    use_free_proxy_pool,
)


@dataclass(frozen=True)
class ImportResult:
    audio_path: str
    title: str
    ext: str
    bytes_downloaded: int
    audio_size_bytes: int
    download_mode: str


def is_supported_url(url: str) -> bool:
    return detect_platform(url) is not None


def _format_error(exc: Exception) -> str:
    parts = [str(arg).strip() for arg in exc.args if str(arg).strip()]
    if parts:
        return "; ".join(parts)
    text = str(exc).strip()
    if text:
        return text
    return type(exc).__name__


def _build_ytdlp_proxies() -> list[str | None]:
    """Proxy attempt order for yt-dlp."""
    attempts: list[str | None] = []
    seen: set[str | None] = set()

    def add(proxy: str | None) -> None:
        key = proxy or "__direct__"
        if key not in seen:
            seen.add(key)
            attempts.append(proxy)

    geonode_proxy = geonode_proxy_url()
    if geonode_proxy:
        for _ in range(geonode_max_attempts()):
            add(geonode_proxy)
        if geonode_allow_direct():
            add(None)
    else:
        add(None)

    if manual_proxy_configured():
        add(get_manual_proxy())
    if use_free_proxy_pool():
        for _ in range(max_attempts()):
            add(get_proxy_url())

    if allow_direct_fallback() and None not in seen:
        add(None)

    return attempts or [None]


def allow_direct_fallback() -> bool:
    from proxy_config import allow_direct_fallback as _allow

    return _allow()


_VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".webm", ".mkv", ".mov", ".avi", ".flv", ".3gp", ".mpeg", ".mpg"}
)


def _download_mode_from_info(info: dict, downloaded_video: bool) -> str:
    """Return audio_only or video_audio_processed."""
    if downloaded_video:
        return "video_audio_processed"

    vcodec = str(info.get("vcodec") or "").strip().lower()
    if vcodec and vcodec != "none":
        return "video_audio_processed"

    if info.get("width") or info.get("height"):
        return "video_audio_processed"

    ext = str(info.get("ext") or "").strip().lower()
    if ext in {"mp4", "webm", "mkv", "mov", "avi", "flv", "3gp"}:
        return "video_audio_processed"

    return "audio_only"


class _DownloadTracker:
    def __init__(self) -> None:
        self.bytes_downloaded = 0
        self.downloaded_video = False

    def hook(self, status: dict) -> None:
        state = status.get("status")
        if state == "finished":
            finished_bytes = status.get("total_bytes")
            filename = status.get("filename")
            if filename:
                ext = os.path.splitext(str(filename))[1].lower()
                if ext in _VIDEO_EXTENSIONS:
                    self.downloaded_video = True
            if not isinstance(finished_bytes, int) or finished_bytes <= 0:
                if filename and os.path.isfile(filename):
                    finished_bytes = os.path.getsize(filename)
            if isinstance(finished_bytes, int) and finished_bytes > 0:
                self.bytes_downloaded += finished_bytes


def _import_via_ytdlp(url: str, tmpdir: str, proxy: str | None) -> ImportResult:
    tracker = _DownloadTracker()
    out_template = os.path.join(tmpdir, "import.%(ext)s")
    socket_timeout = 45 if proxy else 25
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": socket_timeout,
        "progress_hooks": [tracker.hook],
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "192",
            }
        ],
    }

    if proxy:
        ydl_opts["proxy"] = proxy
        print(f"[media-import] yt-dlp via {mask_proxy(proxy)}", flush=True)
    else:
        print("[media-import] yt-dlp direct", flush=True)

    cookies_file = (os.environ.get("YT_DLP_COOKIES_FILE") or "").strip()
    if cookies_file and os.path.isfile(cookies_file):
        ydl_opts["cookiefile"] = cookies_file

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info is None:
            raise RuntimeError("Could not read media from link.")

        title = str(info.get("title") or "imported_audio")
        audio_path = os.path.join(tmpdir, "import.m4a")
        if not os.path.isfile(audio_path):
            candidates = [
                os.path.join(tmpdir, f)
                for f in os.listdir(tmpdir)
                if f.startswith("import.") and not f.endswith(".part")
            ]
            if not candidates:
                raise RuntimeError("Download finished but audio file was not found.")
            audio_path = candidates[0]

        audio_size = os.path.getsize(audio_path)
        if audio_size <= 0:
            raise RuntimeError("Downloaded audio file is empty.")

        ext = os.path.splitext(audio_path)[1].lstrip(".") or "m4a"
        bytes_downloaded = tracker.bytes_downloaded
        if bytes_downloaded <= 0:
            bytes_downloaded = audio_size

        download_mode = _download_mode_from_info(info, tracker.downloaded_video)

        return ImportResult(
            audio_path=audio_path,
            title=title,
            ext=ext if ext != "m4a" else "m4a",
            bytes_downloaded=bytes_downloaded,
            audio_size_bytes=audio_size,
            download_mode=download_mode,
        )


def _import_via_ytdlp_attempts(url: str, tmpdir: str) -> ImportResult:
    attempts = _build_ytdlp_proxies()
    last_error: Exception | None = None

    for attempt_index, proxy in enumerate(attempts, start=1):
        attempt_dir = tmpdir if attempt_index == 1 else os.path.join(tmpdir, f"ytdlp_{attempt_index}")
        if attempt_index > 1:
            os.makedirs(attempt_dir, exist_ok=True)

        try:
            result = _import_via_ytdlp(url, attempt_dir, proxy)
            print(
                f"[media-import] yt-dlp success attempt {attempt_index}/{len(attempts)} "
                f"via {mask_proxy(proxy) or 'direct'} "
                f"bytes_downloaded={result.bytes_downloaded} audio_size={result.audio_size_bytes} "
                f"download_mode={result.download_mode}",
                flush=True,
            )
            return result
        except Exception as e:
            last_error = e
            report_proxy_failure(proxy)
            print(
                f"[media-import] yt-dlp attempt {attempt_index}/{len(attempts)} failed "
                f"({mask_proxy(proxy) or 'direct'}): {_format_error(e)}",
                flush=True,
            )
            if attempt_index > 1 and os.path.isdir(attempt_dir):
                shutil.rmtree(attempt_dir, ignore_errors=True)

    raise RuntimeError(
        _format_error(last_error) if last_error else "All yt-dlp attempts failed."
    )


def import_audio_from_url(url: str, tmpdir: str) -> ImportResult:
    platform = detect_platform(url)
    if not platform:
        raise ValueError(
            "Unsupported URL. Supported: Instagram, YouTube, TikTok, Snapchat public links."
        )

    print(f"[media-import] strategy=ytdlp_only platform={platform}", flush=True)
    return _import_via_ytdlp_attempts(url, tmpdir)
