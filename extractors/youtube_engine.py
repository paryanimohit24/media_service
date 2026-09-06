"""
YouTube Extractor Module
Handles YouTube Videos, Shorts, and Audio with primary yt-dlp, cookies,
proxy pool failover, and NewPipe extractor core secondary fallback.
"""

import re
import logging
from typing import Dict, Any
from extractors.ytdlp_engine import extract_via_ytdlp
from extractors.newpipe_engine import extract_via_newpipe_fallback
from extractors.base_extractor import is_safe_public_url

logger = logging.getLogger("YouTubeExtractor")


async def extract_youtube(url: str, format_type: str = "mp4", client_ip: str = "127.0.0.1") -> Dict[str, Any]:
    """
    Multi-tier YouTube Extraction Pipeline:
    1. Primary yt-dlp with YouTube cookies
    2. Secondary NewPipe Extractor Core fallback
    3. Tertiary rotating proxy failover
    """
    is_safe, reason = is_safe_public_url(url)
    if not is_safe:
        raise Exception(f"YouTube SSRF Security Block: {reason}")

    # Tier 1: Direct yt-dlp with Android client & cookies
    try:
        res = await extract_via_ytdlp(url, format_type, client_ip, use_proxy=False)
        if res and res.get("download_url"):
            return res
    except Exception as e:
        logger.warning(f"YouTube primary extraction notice: {e}")

    # Tier 2: Rotating proxy pool failover
    try:
        res = await extract_via_ytdlp(url, format_type, client_ip, use_proxy=True)
        if res and res.get("download_url"):
            return res
    except Exception as ep:
        logger.warning(f"YouTube proxy pool failover notice: {ep}")

    # Tier 3: JioSaavn Audio Match Fallback (For Audio/MP3 - Fast & No Datacenter IP Blocks)
    if format_type == "mp3":
        try:
            import httpx
            import urllib.parse
            from config import DEFAULT_USER_AGENT, PUBLIC_BASE_URL
            from extractors.spotify_engine import search_and_resolve_jiosaavn

            oembed_url = f"https://www.youtube.com/oembed?url={urllib.parse.quote(url)}&format=json"
            async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
                r_oem = await client.get(oembed_url, headers={"User-Agent": DEFAULT_USER_AGENT})
                if r_oem.status_code == 200:
                    oem_data = r_oem.json()
                    raw_title = oem_data.get("title", "")
                    author = oem_data.get("author_name", "")
                    # Clean title: strip emojis, #shorts, (Official Video), [MV] etc.
                    cleaned_title = re.sub(r'[^\x00-\x7F]+', ' ', raw_title)
                    cleaned_title = re.sub(r'#\w+', ' ', cleaned_title)
                    cleaned_title = re.sub(r'\(.*?\)|\[.*?\]', ' ', cleaned_title)
                    cleaned_title = " ".join(cleaned_title.split()).strip()

                    if cleaned_title:
                        saavn_cand = await search_and_resolve_jiosaavn(cleaned_title, author)
                        if saavn_cand and saavn_cand.get("raw_stream_url"):
                            stream_url = saavn_cand.get("raw_stream_url")
                            encoded_url = urllib.parse.quote(url)
                            encoded_title = urllib.parse.quote(raw_title or cleaned_title)
                            proxy_mp3 = f"{PUBLIC_BASE_URL}/api/download?url={encoded_url}&format_type=mp3&title={encoded_title}"
                            logger.info(f"YouTube Audio matched via JioSaavn: '{cleaned_title}' ({saavn_cand.get('duration')}s)")
                            return {
                                "platform": "YouTube",
                                "title": saavn_cand.get("title") or raw_title,
                                "thumbnail": saavn_cand.get("thumbnail") or oem_data.get("thumbnail_url"),
                                "duration": saavn_cand.get("duration"),
                                "format_type": "mp3",
                                "engine": "YouTube Audio HD Engine (320kbps Stream)",
                                "download_url": proxy_mp3,
                                "raw_stream_url": stream_url,
                                "mp4_url": proxy_mp3,
                                "mp3_url": proxy_mp3,
                                "quality": "320kbps High Quality Audio"
                            }
        except Exception as e_js:
            logger.debug(f"YouTube JioSaavn audio fallback notice: {e_js}")

    # Tier 4: NewPipe Extractor Core fallback
    try:
        res = await extract_via_newpipe_fallback(url, format_type)
        if res and res.get("download_url"):
            return res
    except Exception as e_np:
        logger.warning(f"YouTube NewPipe fallback notice: {e_np}")

    raise Exception(f"Unable to extract media stream for YouTube URL: {url}")
