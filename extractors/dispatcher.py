"""
Media Extraction Dispatcher Module
Central orchestrator that maps target URLs to specialized platform extractors
and manages multi-tier fallback cascades.
"""

import logging
from typing import Dict, Any

from fastapi import HTTPException

from extractors.base_extractor import is_safe_public_url, clean_target_url
from extractors.spotify_engine import extract_spotify
from extractors.reddit_engine import extract_reddit
from extractors.tiktok_engine import extract_tiktok
from extractors.instagram_engine import extract_instagram
from extractors.facebook_engine import extract_facebook
from extractors.pinterest_engine import extract_pinterest
from extractors.youtube_engine import extract_youtube
from extractors.ytdlp_engine import extract_via_ytdlp
from extractors.newpipe_engine import extract_via_newpipe_fallback

logger = logging.getLogger("MediaDispatcher")


async def process_media_extraction(url: str, format_type: str = "mp4", client_ip: str = "127.0.0.1") -> Dict[str, Any]:
    """
    Main extraction pipeline:
    1. Validates URL against SSRF and private subnet access.
    2. Routes to specialized platform extractor (Reddit, Spotify, TikTok, Instagram, Facebook, Pinterest, YouTube).
    3. Executes primary yt-dlp engine with cookie routing.
    4. Executes secondary NewPipe engine fallback.
    5. Executes tertiary rotating proxy pool failover.
    """
    is_safe, reason = is_safe_public_url(url)
    if not is_safe:
        raise HTTPException(status_code=400, detail=f"SSRF Security Block: {reason}")

    cleaned_url = clean_target_url(url)
    url_lower = cleaned_url.lower()

    # 1. Specialized Spotify Extractor
    if "spotify.com" in url_lower:
        return {"success": True, "data": await extract_spotify(cleaned_url, client_ip, format_type)}

    # 2. Specialized Reddit Extractor
    if "reddit.com" in url_lower or "redd.it" in url_lower:
        try:
            return {"success": True, "data": await extract_reddit(cleaned_url, format_type, client_ip)}
        except Exception as e:
            logger.warning(f"Reddit extractor warning: {e}")

    # 3. Specialized TikTok Extractor
    if "tiktok.com" in url_lower:
        try:
            return {"success": True, "data": await extract_tiktok(cleaned_url, format_type, client_ip)}
        except Exception as e:
            logger.warning(f"TikTok extractor warning: {e}")

    # 4. Specialized Instagram Extractor
    if "instagram.com" in url_lower:
        try:
            return {"success": True, "data": await extract_instagram(cleaned_url, format_type, client_ip)}
        except Exception as e:
            logger.warning(f"Instagram extractor warning: {e}")

    # 5. Specialized Facebook Extractor
    if "facebook.com" in url_lower or "fb.watch" in url_lower:
        try:
            return {"success": True, "data": await extract_facebook(cleaned_url, format_type, client_ip)}
        except Exception as e:
            logger.warning(f"Facebook extractor warning: {e}")

    # 6. Specialized Pinterest Extractor
    if "pinterest.com" in url_lower or "pin.it" in url_lower:
        try:
            return {"success": True, "data": await extract_pinterest(cleaned_url, format_type, client_ip)}
        except Exception as e:
            logger.warning(f"Pinterest extractor warning: {e}")

    # 7. Specialized YouTube Extractor
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        try:
            return {"success": True, "data": await extract_youtube(cleaned_url, format_type, client_ip)}
        except Exception as e:
            logger.warning(f"YouTube extractor warning: {e}")

    # 8. Generic Multi-Tier Fallback Cascade
    # Tier 1: Direct yt-dlp
    try:
        res = await extract_via_ytdlp(cleaned_url, format_type, client_ip, use_proxy=False)
        if res and res.get("download_url"):
            return {"success": True, "data": res}
    except Exception as e:
        logger.debug(f"Direct generic yt-dlp notice: {e}")

    # Tier 2: NewPipe Extractor Core
    try:
        res = await extract_via_newpipe_fallback(cleaned_url, format_type)
        if res and res.get("download_url"):
            return {"success": True, "data": res}
    except Exception as e:
        logger.debug(f"Generic NewPipe fallback notice: {e}")

    # Tier 3: Proxy Failover
    try:
        res = await extract_via_ytdlp(cleaned_url, format_type, client_ip, use_proxy=True)
        if res and res.get("download_url"):
            return {"success": True, "data": res}
    except Exception as e:
        logger.error(f"All extraction engines failed for {cleaned_url}: {e}")

    raise HTTPException(status_code=500, detail="Media stream extraction failed across all engines.")
