"""
TikTok Extractor Module
Handles TikTok media extraction with Netscape cookies, mobile shortlink unrolling,
and custom User-Agent/Referer headers.
"""

import logging
from typing import Dict, Any
from extractors.ytdlp_engine import extract_via_ytdlp
from extractors.base_extractor import is_safe_public_url

logger = logging.getLogger("TikTokExtractor")


async def extract_tiktok(url: str, format_type: str = "mp4", client_ip: str = "127.0.0.1") -> Dict[str, Any]:
    """Extracts TikTok video or audio stream using primary yt-dlp engine with TikTok cookies."""
    is_safe, reason = is_safe_public_url(url)
    if not is_safe:
        raise Exception(f"TikTok SSRF Security Block: {reason}")

    # Primary yt-dlp handles TikTok with cookies/tiktok.txt
    return await extract_via_ytdlp(url, format_type, client_ip, use_proxy=False)
