"""
Reddit Extractor Module
Extracts Reddit post audio/video streams using primary engine with Netscape cookies,
and robust short-link unrolling + fallback title resolution.
"""

import logging
import urllib.parse
from typing import Dict, Any
import httpx
from config import PUBLIC_BASE_URL
from extractors.ytdlp_engine import extract_via_ytdlp
from extractors.base_extractor import is_safe_public_url

logger = logging.getLogger("MediaDownloader")


async def extract_reddit(url: str, format_type: str = "mp4", client_ip: str = "127.0.0.1") -> Dict[str, Any]:
    """
    Extracts Reddit post audio/video streams cleanly:
    1. Unrolls short links (/s/...) via Mobile User-Agent / rxddit.
    2. Executes direct yt-dlp extraction with cookies.
    3. Fallback to title slug search if datacenter IP blocked.
    """
    is_safe, reason = is_safe_public_url(url)
    if not is_safe:
        raise Exception(f"Reddit Extractor SSRF Block: {reason}")
    target_url = url
    if "/s/" in url:
        try:
            rx_url = url.replace("www.reddit.com", "rxddit.com").replace("reddit.com", "rxddit.com")
            headers = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"}
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=False, headers=headers) as client:
                res = await client.get(rx_url)
                loc = res.headers.get("location") or str(res.url)
                if "comments" in loc:
                    target_url = loc.replace("rxddit.com", "www.reddit.com").split("?")[0]
        except Exception as unroll_err:
            logger.warning(f"Reddit short link unroll warning: {unroll_err}")

    # Primary Direct Extraction
    try:
        return await extract_via_ytdlp(target_url, format_type, client_ip, use_proxy=False)
    except Exception as e:
        logger.warning(f"Reddit direct extraction notice ({e}), executing fallback resolution pipeline...")

    clean_url = target_url.split("?")[0].rstrip("/")
    parts = [p for p in clean_url.split("/") if p]
    
    query_title = "Reddit Media Track"
    if "comments" in parts:
        idx = parts.index("comments")
        if len(parts) > idx + 2:
            query_title = parts[idx + 2].replace("_", " ").title()
    elif len(parts) > 0:
        query_title = parts[-1].replace("_", " ").title()

    logger.info(f"Reddit Fallback Query Title: '{query_title}'")

    res = None
    try:
        res = await extract_via_ytdlp(f"scsearch:{query_title}", format_type, client_ip, use_proxy=False)
    except Exception:
        pass

    if not res:
        try:
            res = await extract_via_ytdlp(f"ytsearch5:{query_title}", format_type, client_ip, use_proxy=False)
        except Exception:
            pass

    if not res:
        try:
            res = await extract_via_ytdlp(f"ytsearch:{query_title}", format_type, client_ip, use_proxy=False)
        except Exception:
            pass

    encoded_url = urllib.parse.quote(target_url)
    encoded_title = urllib.parse.quote(query_title)
    proxy_mp4 = f"{PUBLIC_BASE_URL}/api/download?url={encoded_url}&format_type=mp4&title={encoded_title}"
    proxy_mp3 = f"{PUBLIC_BASE_URL}/api/download?url={encoded_url}&format_type=mp3&title={encoded_title}"

    return {
        "platform": "Reddit",
        "title": query_title,
        "thumbnail": res.get("thumbnail") if res else "https://www.redditstatic.com/icon.png",
        "duration": res.get("duration") if res else 0,
        "format_type": format_type,
        "engine": "Reddit Stream Extractor Engine" if res else "Reddit Post Engine",
        "download_url": proxy_mp3 if format_type == "mp3" else proxy_mp4,
        "raw_stream_url": res.get("raw_stream_url") if res else target_url,
        "mp4_url": proxy_mp4,
        "mp3_url": proxy_mp3,
        "quality": "HD Stream" if format_type == "mp4" else "320kbps Audio"
    }
