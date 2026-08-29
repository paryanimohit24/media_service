"""Download audio from supported social URLs via yt-dlp (direct first; optional proxy later)."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

import yt_dlp

from http_headers import mobile_user_agent
from media_download import media_to_m4a
from page_parser import detect_platform
from youtube_innertube import fetch_youtube_audio_url, youtube_video_id
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


_YOUTUBE_CLIENTS = (
    "android_sdkless",
    "tv_embedded",
    "web_embedded",
    "android",
    "ios",
    "mweb",
    "tv",
    "web_safari",
    "web",
    "android_vr",
    "tv_simply",
)


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


def allow_direct_fallback() -> bool:
    from proxy_config import allow_direct_fallback as _allow

    return _allow()


def _variant_count(platform: str) -> int:
    if platform == "youtube":
        return len(_YOUTUBE_CLIENTS)
    if platform == "tiktok":
        return 4
    if platform == "snapchat":
        return 2
    return 1


def _build_ytdlp_proxies() -> list[str | None]:
    """Proxy attempt order: direct first, then optional manual/free proxies."""
    attempts: list[str | None] = []
    seen: set[str | None] = set()

    def add(proxy: str | None) -> None:
        key = proxy or "__direct__"
        if key not in seen:
            seen.add(key)
            attempts.append(proxy)

    add(None)

    if manual_proxy_configured():
        add(get_manual_proxy())
    if use_free_proxy_pool():
        for _ in range(max_attempts()):
            add(get_proxy_url())

    if allow_direct_fallback() and None not in seen:
        add(None)

    return attempts or [None]


_VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".webm", ".mkv", ".mov", ".avi", ".flv", ".3gp", ".mpeg", ".mpg"}
)


def _download_mode_from_info(info: dict, downloaded_video: bool) -> str:
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


def _build_ydl_opts(
    platform: str,
    tmpdir: str,
    proxy: str | None,
    tracker: _DownloadTracker,
    variant: int = 0,
) -> dict:
    ua = mobile_user_agent()
    out_template = os.path.join(tmpdir, "import.%(ext)s")
    socket_timeout = 90 if proxy else 60
    opts: dict = {
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": socket_timeout,
        "user_agent": ua,
        "progress_hooks": [tracker.hook],
        "retries": 3,
        "fragment_retries": 3,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "192",
            }
        ],
    }

    if platform == "youtube":
        client = _YOUTUBE_CLIENTS[variant % len(_YOUTUBE_CLIENTS)]
        opts["extractor_args"] = {"youtube": {"player_client": [client]}}
        print(f"[media-import] youtube player_client={client}", flush=True)
    elif platform == "tiktok":
        impersonates = ["chrome", "safari15_5", "chrome", "safari15_5"]
        opts["http_headers"] = {
            "User-Agent": ua,
            "Referer": "https://www.tiktok.com/",
        }
        opts["impersonate"] = impersonates[variant % len(impersonates)]
    elif platform == "snapchat":
        opts["http_headers"] = {"User-Agent": ua}
        if variant % 2 == 0:
            opts["impersonate"] = "chrome"
    elif platform == "instagram":
        opts["http_headers"] = {"User-Agent": ua}
    elif platform == "facebook":
        opts["http_headers"] = {
            "User-Agent": ua,
            "Referer": "https://www.facebook.com/",
        }

    if proxy:
        opts["proxy"] = proxy

    cookies_file = (os.environ.get("YT_DLP_COOKIES_FILE") or "").strip()
    if cookies_file and os.path.isfile(cookies_file):
        opts["cookiefile"] = cookies_file

    return opts


def _import_via_ytdlp(
    url: str,
    tmpdir: str,
    proxy: str | None,
    platform: str,
    variant: int = 0,
) -> ImportResult:
    tracker = _DownloadTracker()
    ydl_opts = _build_ydl_opts(platform, tmpdir, proxy, tracker, variant=variant)

    if proxy:
        print(f"[media-import] yt-dlp via {mask_proxy(proxy)}", flush=True)
    else:
        print("[media-import] yt-dlp direct", flush=True)

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


def _import_via_ytdlp_attempts(url: str, tmpdir: str, platform: str) -> ImportResult:
    proxies = _build_ytdlp_proxies()
    variants = _variant_count(platform)
    last_error: Exception | None = None
    attempt_index = 0
    total_attempts = len(proxies) * variants

    for proxy in proxies:
        for variant in range(variants):
            attempt_index += 1
            attempt_dir = (
                tmpdir
                if attempt_index == 1
                else os.path.join(tmpdir, f"ytdlp_{attempt_index}")
            )
            if attempt_index > 1:
                os.makedirs(attempt_dir, exist_ok=True)

            try:
                result = _import_via_ytdlp(url, attempt_dir, proxy, platform, variant=variant)
                print(
                    f"[media-import] yt-dlp success attempt {attempt_index}/{total_attempts} "
                    f"via {mask_proxy(proxy) or 'direct'} variant={variant} "
                    f"bytes_downloaded={result.bytes_downloaded} audio_size={result.audio_size_bytes} "
                    f"download_mode={result.download_mode}",
                    flush=True,
                )
                return result
            except Exception as e:
                last_error = e
                report_proxy_failure(proxy)
                print(
                    f"[media-import] yt-dlp attempt {attempt_index}/{total_attempts} failed "
                    f"({mask_proxy(proxy) or 'direct'} variant={variant}): {_format_error(e)}",
                    flush=True,
                )
                if attempt_index > 1 and os.path.isdir(attempt_dir):
                    shutil.rmtree(attempt_dir, ignore_errors=True)

    if last_error:
        print(
            f"[media-import] yt-dlp all attempts failed ({platform}): {_format_error(last_error)}",
            flush=True,
        )

    raise RuntimeError(
        _format_error(last_error) if last_error else "All yt-dlp attempts failed."
    )


def _import_via_innertube_youtube(url: str, tmpdir: str) -> ImportResult | None:
    video_id = youtube_video_id(url)
    if not video_id:
        return None

    proxies = _build_ytdlp_proxies()
    last_error: Exception | None = None
    for attempt_index, proxy in enumerate(proxies, start=1):
        try:
            audio_url = fetch_youtube_audio_url(video_id, proxy=proxy)
            if not audio_url:
                continue
            attempt_dir = (
                tmpdir
                if attempt_index == 1
                else os.path.join(tmpdir, f"innertube_{attempt_index}")
            )
            if attempt_index > 1:
                os.makedirs(attempt_dir, exist_ok=True)

            audio_path, bytes_downloaded, download_mode = media_to_m4a(
                audio_url,
                attempt_dir,
                proxy=proxy,
                referer=f"https://www.youtube.com/watch?v={video_id}",
            )
            audio_size = os.path.getsize(audio_path)
            if audio_size <= 0:
                raise RuntimeError("Innertube audio file is empty.")
            print(
                f"[media-import] innertube success via {mask_proxy(proxy) or 'direct'} "
                f"bytes_downloaded={bytes_downloaded} audio_size={audio_size}",
                flush=True,
            )
            return ImportResult(
                audio_path=audio_path,
                title=f"youtube_{video_id}",
                ext="m4a",
                bytes_downloaded=bytes_downloaded,
                audio_size_bytes=audio_size,
                download_mode=download_mode,
            )
        except Exception as e:
            last_error = e
            report_proxy_failure(proxy)
            print(
                f"[media-import] innertube attempt {attempt_index}/{len(proxies)} failed "
                f"({mask_proxy(proxy) or 'direct'}): {_format_error(e)}",
                flush=True,
            )
            if attempt_index > 1 and os.path.isdir(attempt_dir):
                shutil.rmtree(attempt_dir, ignore_errors=True)

    if last_error:
        print(f"[media-import] innertube all attempts failed: {_format_error(last_error)}", flush=True)
    return None


def import_audio_from_url(url: str, tmpdir: str) -> ImportResult:
    platform = detect_platform(url)
    if not platform:
        raise ValueError(
            "Unsupported URL. Supported: Instagram, YouTube, TikTok, Snapchat, Facebook public links."
        )

    if platform == "youtube":
        print(f"[media-import] strategy=innertube_then_ytdlp platform={platform}", flush=True)
        try:
            innertube_result = _import_via_innertube_youtube(url, tmpdir)
            if innertube_result is not None:
                print("[media-import] success via youtube innertube", flush=True)
                return innertube_result
        except Exception as e:
            print(f"[media-import] innertube failed: {_format_error(e)}", flush=True)

    print(f"[media-import] strategy=ytdlp_direct platform={platform}", flush=True)
    return _import_via_ytdlp_attempts(url, tmpdir, platform)
