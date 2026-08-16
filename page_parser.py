"""Detect supported social URL platforms."""
from __future__ import annotations

import re
from urllib.parse import urlparse

_INSTAGRAM_SHORTCODE = re.compile(
    r"instagram\.com/(?:reel|reels|p|tv)/([\w-]+)",
    re.IGNORECASE,
)


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

    return None


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
