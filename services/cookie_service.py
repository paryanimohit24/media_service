"""
Cookie Service Module
Manages platform-specific Netscape HTTP cookie file mappings and resolution.
"""

import os
import logging
from typing import Optional, Dict

logger = logging.getLogger("CookieService")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COOKIES_DIR = os.path.join(BASE_DIR, "cookies")
GLOBAL_COOKIES_FILE = os.path.join(BASE_DIR, "cookies.txt")

# Platform-specific cookie file mappings
PLATFORM_COOKIE_MAP: Dict[str, str] = {
    "youtube": os.path.join(COOKIES_DIR, "youtube.txt"),
    "youtu.be": os.path.join(COOKIES_DIR, "youtube.txt"),
    "facebook": os.path.join(COOKIES_DIR, "facebook.txt"),
    "fb.watch": os.path.join(COOKIES_DIR, "facebook.txt"),
    "instagram": os.path.join(COOKIES_DIR, "instagram.txt"),
    "reddit": os.path.join(COOKIES_DIR, "reddit.txt"),
    "redd.it": os.path.join(COOKIES_DIR, "reddit.txt"),
    "pinterest": os.path.join(COOKIES_DIR, "pinterest.txt"),
    "pin.it": os.path.join(COOKIES_DIR, "pinterest.txt"),
    "tiktok": os.path.join(COOKIES_DIR, "tiktok.txt"),
    "snapchat": os.path.join(COOKIES_DIR, "snapchat.txt"),
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
