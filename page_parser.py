"""Parse media URLs from scraped HTML."""
from __future__ import annotations

import re
from urllib.parse import urlparse

_OG_VIDEO_SECURE = re.compile(
    r'property="og:video:secure_url"\s+content="([^"]+)"',
    re.IGNORECASE,
)
_OG_VIDEO_SECURE_ALT = re.compile(
    r'content="([^"]+)"\s+property="og:video:secure_url"',
    re.IGNORECASE,
)
_OG_VIDEO = re.compile(
    r'property="og:video"\s+content="([^"]+)"',
    re.IGNORECASE,
)
_OG_VIDEO_ALT = re.compile(
    r'content="([^"]+)"\s+property="og:video"',
    re.IGNORECASE,
)
_JSON_AUDIO_URL = re.compile(r'"audio_url"\s*:\s*"([^"]+)"', re.IGNORECASE)
_JSON_VIDEO_URL = re.compile(r'"video_url"\s*:\s*"([^"]+)"', re.IGNORECASE)
_TIKTOK_PLAY = re.compile(r'"playAddr"\s*:\s*"([^"]+)"', re.IGNORECASE)
_TIKTOK_DOWNLOAD = re.compile(r'"downloadAddr"\s*:\s*"([^"]+)"', re.IGNORECASE)
_CONTENT_URL = re.compile(r'"contentUrl"\s*:\s*"([^"]+)"', re.IGNORECASE)
_SNAPCHAT_MEDIA = re.compile(r'"mediaUrl"\s*:\s*"([^"]+)"', re.IGNORECASE)

_INSTAGRAM_SHORTCODE = re.compile(
    r"instagram\.com/(?:reel|reels|p|tv)/([\w-]+)",
    re.IGNORECASE,
)


def _unescape_json_url(raw: str) -> str:
    return (
        raw.replace("\\u0026", "&")
        .replace("\\/", "/")
        .replace("\\\\", "\\")
        .replace("&amp;", "&")
    )


def _add_candidate(candidates: list[str], raw: str | None) -> None:
    if not raw:
        return
    decoded = _unescape_json_url(raw.strip())
    if decoded.startswith("http"):
        candidates.append(decoded)


def parse_media_url(html: str, platform: str | None = None) -> str | None:
    """Return best direct media URL found in HTML."""
    candidates: list[str] = []

    patterns = [
        _OG_VIDEO_SECURE,
        _OG_VIDEO_SECURE_ALT,
        _OG_VIDEO,
        _OG_VIDEO_ALT,
        _JSON_AUDIO_URL,
        _JSON_VIDEO_URL,
        _TIKTOK_PLAY,
        _TIKTOK_DOWNLOAD,
        _CONTENT_URL,
        _SNAPCHAT_MEDIA,
    ]
    for pattern in patterns:
        for match in pattern.finditer(html):
            _add_candidate(candidates, match.group(1))

    if not candidates:
        return None

    if platform == "instagram" or platform is None:
        audio = [
            u
            for u in candidates
            if "audio" in u.lower() or u.lower().endswith(".m4a")
        ]
        if audio:
            return audio[0]

    videoish = [u for u in candidates if any(x in u.lower() for x in (".mp4", "video", "cdninstagram"))]
    if videoish:
        return videoish[0]

    return candidates[0]


def instagram_fetch_urls(page_url: str) -> list[str]:
    """URLs to scrape for Instagram reel/post (page + embed)."""
    urls = [page_url.strip()]
    match = _INSTAGRAM_SHORTCODE.search(page_url)
    if match:
        shortcode = match.group(1)
        embed = f"https://www.instagram.com/reel/{shortcode}/embed/"
        if embed not in urls:
            urls.append(embed)
    return urls


def detect_platform(url: str) -> str | None:
    raw = (url or "").strip()
    if not raw.startswith(("http://", "https://")):
        return None
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""

    if host in ("instagram.com", "www.instagram.com", "instagr.am", "www.instagr.am"):
        if re.match(r"^/(reel|reels|p|tv)/[\w-]+", path, re.IGNORECASE):
            return "instagram"

    if host in ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"):
        if host == "youtu.be" and path and path != "/":
            return "youtube"
        if re.match(r"^/(watch|shorts|embed)(/|$)", path, re.IGNORECASE):
            return "youtube"
        if path.lower().startswith("/watch"):
            return "youtube"

    if host.endswith("tiktok.com") or host == "vm.tiktok.com":
        return "tiktok"

    if host.endswith("snapchat.com"):
        return "snapchat"

    return None
