"""Native page-scrape import — same approach as the Flutter ReelClientImportService."""
from __future__ import annotations

import os
import re
import urllib.request

from http_headers import mobile_user_agent
from media_download import media_to_m4a
from page_parser import parse_media_url, platform_fetch_urls

_OG_TITLE = re.compile(
    r'property="og:title"\s+content="([^"]+)"',
    re.IGNORECASE,
)
_OG_TITLE_ALT = re.compile(
    r'content="([^"]+)"\s+property="og:title"',
    re.IGNORECASE,
)


def _fetch_page(url: str, platform: str) -> str | None:
    headers = {
        "User-Agent": mobile_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if platform == "tiktok":
        headers["Referer"] = "https://www.tiktok.com/"
    elif platform == "youtube":
        headers["Referer"] = "https://www.youtube.com/"
    elif platform == "snapchat":
        headers["Referer"] = "https://www.snapchat.com/"
    elif platform == "facebook":
        headers["Referer"] = "https://www.facebook.com/"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status and resp.status >= 400:
                return None
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def _title_from_html(html: str, platform: str) -> str:
    for pattern in (_OG_TITLE, _OG_TITLE_ALT):
        match = pattern.search(html)
        if match:
            title = match.group(1).strip()
            if title:
                return title
    return f"{platform}_import"


def import_via_native_extractor(
    url: str,
    tmpdir: str,
    platform: str,
) -> tuple[str, str, int, int, str]:
    """Return (audio_path, title, bytes_downloaded, audio_size_bytes, download_mode)."""
    fetch_urls = platform_fetch_urls(url, platform)
    html: str | None = None
    for fetch_url in fetch_urls:
        html = _fetch_page(fetch_url, platform)
        if html:
            break

    if not html:
        raise RuntimeError("Could not load page HTML.")

    media_url = parse_media_url(html, platform)
    if not media_url:
        raise RuntimeError("Could not find media URL in page.")

    title = _title_from_html(html, platform)
    print(
        f"[media-import] native resolved platform={platform} title={title!r}",
        flush=True,
    )

    referer = fetch_urls[0]
    audio_path, bytes_downloaded, download_mode = media_to_m4a(
        media_url,
        tmpdir,
        proxy=None,
        referer=referer,
    )
    audio_size = os.path.getsize(audio_path)
    if audio_size <= 0:
        raise RuntimeError("Native download produced an empty audio file.")

    return audio_path, title, bytes_downloaded, audio_size, download_mode
