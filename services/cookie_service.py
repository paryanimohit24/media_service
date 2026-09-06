"""
Cookie Service Module
Manages platform-specific Netscape HTTP cookie file mappings and resolution.
"""

import os
import logging
from typing import Optional, Dict

logger = logging.getLogger("CookieService")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env_cookies_dir = os.getenv("COOKIES_DIR", "").strip()
COOKIES_DIR = _env_cookies_dir if _env_cookies_dir else os.path.join(BASE_DIR, "cookies")
GLOBAL_COOKIES_FILE = os.getenv("COOKIES_FILE", os.path.join(BASE_DIR, "cookies.txt"))

# Platform-specific cookie file mappings
def _cookie_path(name: str) -> str:
    return os.path.join(COOKIES_DIR, name)


PLATFORM_COOKIE_MAP: Dict[str, str] = {
    "youtube": _cookie_path("youtube.txt"),
    "youtu.be": _cookie_path("youtube.txt"),
    "facebook": _cookie_path("facebook.txt"),
    "fb.watch": _cookie_path("facebook.txt"),
    "instagram": _cookie_path("instagram.txt"),
    "reddit": _cookie_path("reddit.txt"),
    "redd.it": _cookie_path("reddit.txt"),
    "pinterest": _cookie_path("pinterest.txt"),
    "pin.it": _cookie_path("pinterest.txt"),
    "tiktok": _cookie_path("tiktok.txt"),
    "snapchat": _cookie_path("snapchat.txt"),
}


def get_cookie_file_for_url(url: str) -> Optional[str]:
    """
    Returns the absolute path to a valid, non-empty cookie file for the target URL.
    Falls back to global cookies.txt if available.
    """
    if not url:
        return None

    url_lower = url.lower()
    for domain_key, path in PLATFORM_COOKIE_MAP.items():
        if domain_key in url_lower and os.path.exists(path) and os.path.getsize(path) > 10:
            return path

    # Global fallback if available
    if os.path.exists(GLOBAL_COOKIES_FILE) and os.path.getsize(GLOBAL_COOKIES_FILE) > 10:
        return GLOBAL_COOKIES_FILE

    return None
