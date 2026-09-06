"""
Facebook Extractor Module
Handles Facebook Videos, Reels, and Watch links with shortlink unrolling and cookies.
"""

import logging
import httpx
from typing import Dict, Any
from config import DEFAULT_USER_AGENT
from extractors.ytdlp_engine import extract_via_ytdlp
from extractors.base_extractor import is_safe_public_url

logger = logging.getLogger("FacebookExtractor")


async def extract_facebook(url: str, format_type: str = "mp4", client_ip: str = "127.0.0.1") -> Dict[str, Any]:
    """Extracts Facebook video stream with cookies and shortlink resolution."""
    is_safe, reason = is_safe_public_url(url)
    if not is_safe:
        raise Exception(f"Facebook SSRF Security Block: {reason}")

    target_url = url
    if "/share/" in target_url or "fb.watch" in target_url:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=8.0) as client:
                res = await client.get(target_url, headers={"User-Agent": DEFAULT_USER_AGENT})
                target_url = str(res.url)
        except Exception:
            pass

    return await extract_via_ytdlp(target_url, format_type, client_ip, use_proxy=False)
