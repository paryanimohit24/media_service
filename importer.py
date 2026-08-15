"""Download audio from supported social URLs via yt-dlp."""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass

import yt_dlp

from free_proxy_pool import auto_proxy_enabled, next_fallback_proxies
from proxy_config import (
    get_manual_proxy,
    get_proxy_url,
    manual_proxy_configured,
    mask_proxy,
    max_attempts,
    proxy_fallback_attempts,
    report_proxy_failure,
)

INSTAGRAM_HOSTS = ("instagram.com", "www.instagram.com", "instagr.am", "www.instagr.am")
INSTAGRAM_PATH = re.compile(r"^/(reel|reels|p|tv)/[\w-]+", re.IGNORECASE)


@dataclass(frozen=True)
class ImportResult:
    audio_path: str
    title: str
    ext: str


def is_supported_url(url: str) -> bool:
    raw = (url or "").strip()
    if not raw.startswith(("http://", "https://")):
        return False
    try:
        from urllib.parse import urlparse

        parsed = urlparse(raw)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    if host not in INSTAGRAM_HOSTS:
        return False
    path = parsed.path or ""
    return bool(INSTAGRAM_PATH.match(path))


def _build_attempt_proxies() -> list[str | None]:
    """Order: direct (Cloud Run IP) → manual admin proxy → free pool."""
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

    if auto_proxy_enabled():
        for _ in range(max_attempts()):
            add(get_proxy_url())
    else:
        fb = proxy_fallback_attempts()
        if fb > 0:
            for proxy in next_fallback_proxies(fb):
                add(proxy)

    return attempts or [None]


def _format_error(exc: Exception) -> str:
    parts = [str(arg).strip() for arg in exc.args if str(arg).strip()]
    if parts:
        return "; ".join(parts)
    text = str(exc).strip()
    if text:
        return text
    return type(exc).__name__


def _import_once(url: str, tmpdir: str, proxy: str | None) -> ImportResult:
    out_template = os.path.join(tmpdir, "import.%(ext)s")
    socket_timeout = 25 if proxy else 20
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": socket_timeout,
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
        print(f"[media-import] trying proxy {mask_proxy(proxy)}", flush=True)
    else:
        print("[media-import] trying direct (no proxy)", flush=True)

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

        ext = os.path.splitext(audio_path)[1].lstrip(".") or "m4a"
        return ImportResult(audio_path=audio_path, title=title, ext=ext if ext != "m4a" else "m4a")


def import_audio_from_url(url: str, tmpdir: str) -> ImportResult:
    if not is_supported_url(url):
        raise ValueError("Only public Instagram reel/post links are supported.")

    attempts = _build_attempt_proxies()
    last_error: Exception | None = None

    for attempt_index, proxy in enumerate(attempts, start=1):
        attempt_dir = tmpdir if attempt_index == 1 else os.path.join(tmpdir, f"try_{attempt_index}")
        if attempt_index > 1:
            os.makedirs(attempt_dir, exist_ok=True)

        try:
            result = _import_once(url, attempt_dir, proxy)
            print(
                f"[media-import] success on attempt {attempt_index}/{len(attempts)} "
                f"via {mask_proxy(proxy) or 'direct'}",
                flush=True,
            )
            return result
        except Exception as e:
            last_error = e
            report_proxy_failure(proxy)
            err_text = _format_error(e)
            print(
                f"[media-import] attempt {attempt_index}/{len(attempts)} failed "
                f"({mask_proxy(proxy) or 'direct'}): {err_text}",
                flush=True,
            )
            if attempt_index > 1 and os.path.isdir(attempt_dir):
                shutil.rmtree(attempt_dir, ignore_errors=True)

    raise RuntimeError(
        _format_error(last_error) if last_error else "All proxy attempts failed."
    )
