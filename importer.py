"""Download audio from supported social URLs (Geonode Scraper API + yt-dlp)."""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass

import yt_dlp

from geonode_client import GeonodeError, extract_html
from geonode_config import (
    geonode_allow_direct,
    geonode_enabled,
    geonode_max_attempts,
    geonode_proxy_url,
)
from media_download import media_to_m4a
from page_parser import detect_platform, instagram_fetch_urls, parse_media_url
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
    """Proxy attempt order for yt-dlp. Geonode mode skips direct server IP."""
    attempts: list[str | None] = []
    seen: set[str | None] = set()

    def add(proxy: str | None) -> None:
        key = proxy or "__direct__"
        if key not in seen:
            seen.add(key)
            attempts.append(proxy)

    if geonode_enabled():
        geonode_proxy = geonode_proxy_url()
        if geonode_proxy:
            for _ in range(geonode_max_attempts()):
                add(geonode_proxy)
        elif not geonode_allow_direct():
            # Scraper API only — yt-dlp without proxy is last resort when allowed.
            pass
        else:
            add(None)

        if manual_proxy_configured():
            add(get_manual_proxy())
    else:
        add(None)
        if manual_proxy_configured():
            add(get_manual_proxy())
        if use_free_proxy_pool():
            for _ in range(max_attempts()):
                add(get_proxy_url())

    return attempts or [None]


def geonode_allow_direct_fallback() -> bool:
    return geonode_allow_direct()


def _import_via_geonode_scrape(url: str, tmpdir: str, platform: str) -> ImportResult:
    fetch_urls = instagram_fetch_urls(url) if platform == "instagram" else [url]
    last_error: Exception | None = None

    for fetch_url in fetch_urls:
        try:
            html = extract_html(fetch_url)
            media_url = parse_media_url(html, platform=platform)
            if not media_url:
                raise RuntimeError("Could not find media URL in scraped page.")

            print(
                f"[media-import] geonode scrape resolved media for {platform}",
                flush=True,
            )
            audio_path = media_to_m4a(media_url, tmpdir, proxy=None)
            title = _title_from_url(url, platform)
            return ImportResult(audio_path=audio_path, title=title, ext="m4a")
        except (GeonodeError, Exception) as e:
            last_error = e
            print(
                f"[media-import] geonode scrape failed for {fetch_url}: {_format_error(e)}",
                flush=True,
            )

    raise RuntimeError(
        _format_error(last_error) if last_error else "Geonode scrape did not return media."
    )


def _title_from_url(url: str, platform: str) -> str:
    slug = re.sub(r"[^\w-]", "_", url.rsplit("/", 1)[-1]).strip("_")
    if not slug:
        slug = platform
    return f"{platform}_{slug}"[:80]


def _import_via_ytdlp(url: str, tmpdir: str, proxy: str | None) -> ImportResult:
    out_template = os.path.join(tmpdir, "import.%(ext)s")
    socket_timeout = 45 if proxy else 25
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

        ext = os.path.splitext(audio_path)[1].lstrip(".") or "m4a"
        return ImportResult(audio_path=audio_path, title=title, ext=ext if ext != "m4a" else "m4a")


def import_audio_from_url(url: str, tmpdir: str) -> ImportResult:
    platform = detect_platform(url)
    if not platform:
        raise ValueError(
            "Unsupported URL. Supported: Instagram, YouTube, TikTok, Snapchat public links."
        )

    # 1) Geonode Scraper API (residential proxy page fetch → parse → CDN download)
    if geonode_enabled():
        try:
            result = _import_via_geonode_scrape(url, tmpdir, platform)
            print(f"[media-import] success via geonode-scrape ({platform})", flush=True)
            return result
        except Exception as e:
            print(
                f"[media-import] geonode scrape path failed ({platform}): {_format_error(e)}",
                flush=True,
            )

    # 2) yt-dlp with Geonode/manual/free proxies (no direct IP when Geonode disallows it)
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
                f"via {mask_proxy(proxy) or 'direct'}",
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
        _format_error(last_error) if last_error else "All import attempts failed."
    )
