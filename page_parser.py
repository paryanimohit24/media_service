"""Platform detection and media URL parsing from page HTML."""
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
_GOOGLEVIDEO_PLAYBACK = re.compile(
    r'https?://[^"\s<>]+googlevideo\.com/videoplayback[^"\s<>]*',
    re.IGNORECASE,
)

_INSTAGRAM_SHORTCODE = re.compile(
    r"instagram\.com/(?:reel|reels|p|tv)/([\w-]+)",
    re.IGNORECASE,
)
_YOUTUBE_ID = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/|live/)|youtu\.be/)([\w-]{6,})",
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
    if decoded.startswith("http") and _is_valid_media_url(decoded):
        candidates.append(decoded)


def _is_valid_media_url(url: str) -> bool:
    lower = url.lower()
    if "youtube.com/embed" in lower or "youtube.com/watch" in lower:
        return False
    if "googlevideo.com" in lower:
        if "generate_204" in lower or "initplayback" in lower:
            return False
        return "videoplayback" in lower or ".mp4" in lower
    if any(x in lower for x in ("initplayback", "generate_204", "ytimg.com")):
        return False
    return True


def parse_media_url(html: str, platform: str | None = None) -> str | None:
    """Return best direct media URL found in HTML."""
    candidates: list[str] = []

    for match in _GOOGLEVIDEO_PLAYBACK.finditer(html):
        _add_candidate(candidates, match.group(0))

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

    if platform in ("instagram", "youtube", "tiktok", "snapchat", None):
        audio = [
            u
            for u in candidates
            if "audio" in u.lower()
            or u.lower().endswith(".m4a")
            or "mime=audio" in u.lower()
        ]
        if audio:
            return audio[0]

    googlevideo = [u for u in candidates if "googlevideo.com/videoplayback" in u.lower()]
    if googlevideo:
        return googlevideo[0]

    videoish = [
        u
        for u in candidates
        if any(
            x in u.lower()
            for x in (".mp4", "video", "cdninstagram", "googlevideo", "tiktokcdn")
        )
    ]
    if videoish:
        return videoish[0]

    return candidates[0]


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

    if host.endswith("youtube.com") or host == "youtu.be":
        if host == "youtu.be" and path and path != "/":
            return "youtube"
        if re.match(r"^/(watch|shorts|embed|live)(/|$)", path, re.IGNORECASE):
            return "youtube"
        if path.lower().startswith("/watch"):
            return "youtube"

    if host.endswith("tiktok.com"):
        return "tiktok"

    if host.endswith("snapchat.com"):
        return "snapchat"

    if host in ("fb.watch", "www.fb.watch"):
        return "facebook"

    if host.endswith("facebook.com") or host.endswith("fb.com"):
        if re.match(
            r"^/(watch|reel|reels|videos|share|r|video)(/|$)",
            path,
            re.IGNORECASE,
        ):
            return "facebook"
        if "/watch" in path.lower() or "/reel" in path.lower() or "/videos/" in path.lower():
            return "facebook"

    return None


def youtube_video_id(url: str) -> str | None:
    match = _YOUTUBE_ID.search(url)
    return match.group(1) if match else None


def instagram_fetch_urls(page_url: str) -> list[str]:
    urls = [page_url.strip()]
    match = _INSTAGRAM_SHORTCODE.search(page_url)
    if match:
        shortcode = match.group(1)
        embed = f"https://www.instagram.com/reel/{shortcode}/embed/"
        if embed not in urls:
            urls.append(embed)
    return urls


def platform_fetch_urls(page_url: str, platform: str) -> list[str]:
    """URLs to fetch/scrape per platform (page + embed variants)."""
    urls = [page_url.strip()]
    if platform == "instagram":
        return instagram_fetch_urls(page_url)

    if platform == "youtube":
        vid = youtube_video_id(page_url)
        if vid:
            for extra in (
                f"https://www.youtube.com/embed/{vid}",
                f"https://www.youtube.com/watch?v={vid}",
            ):
                if extra not in urls:
                    urls.append(extra)

    return urls
