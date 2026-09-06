"""
Instagram Extractor Module
Handles Instagram Reels, Posts, and Stories extraction with authenticated cookies
and extractor-specific args (rhots=True).
"""

import logging
from typing import Dict, Any
from extractors.ytdlp_engine import extract_via_ytdlp
from extractors.base_extractor import is_safe_public_url

logger = logging.getLogger("InstagramExtractor")


async def extract_instagram(url: str, format_type: str = "mp4", client_ip: str = "127.0.0.1") -> Dict[str, Any]:
    """Extracts Instagram Reel or Post using primary yt-dlp engine with Instagram cookies."""
    is_safe, reason = is_safe_public_url(url)
    if not is_safe:
        raise Exception(f"Instagram SSRF Security Block: {reason}")

    canonical_url = url.replace("instagram.com/reels/", "instagram.com/reel/")
    return await extract_via_ytdlp(canonical_url, format_type, client_ip, use_proxy=False)
