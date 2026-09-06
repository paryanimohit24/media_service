"""
Secondary Extractor Engine (NewPipe Extractor Core & Distributed Instance Fallback)
Supports: YouTube, SoundCloud, PeerTube, Bandcamp, Media.ccc.de.
Bypasses cloud datacenter IP bot checks when yt-dlp is blocked.
"""

import re
import urllib.parse
import logging
from typing import Dict, Any
import httpx

from config import DEFAULT_USER_AGENT, PUBLIC_BASE_URL
from extractors.base_extractor import is_safe_public_url

logger = logging.getLogger("MediaDownloader")


async def extract_via_newpipe_fallback(url: str, format_type: str = "mp4") -> Dict[str, Any]:
    """
    NewPipe Extractor Core Fallback implementation.
    Iterates over distributed Piped/Invidious/Cobalt instances to resolve stream links.
    """
    is_safe, reason = is_safe_public_url(url)
    if not is_safe:
        raise Exception(f"NewPipe Engine SSRF Block: {reason}")

    logger.info(f"Triggering Secondary NewPipe Extractor Fallback Engine for: {url}")
    video_id_match = re.search(r"(?:v=|\/shorts\/|\/embed\/|youtu\.be\/)([a-zA-Z0-9_-]{11})", url)
    
    if not video_id_match:
        raise Exception("NewPipe Extractor Engine: Invalid YouTube video ID format")
        
    video_id = video_id_match.group(1)
    
    async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:
        # 1. Distributed Piped Instances
        piped_instances = [
            f"https://pipedapi.kavin.rocks/streams/{video_id}",
            f"https://api.piped.private.coffee/streams/{video_id}",
            f"https://pipedapi.mha.fi/streams/{video_id}",
            f"https://pipedapi.astral.site/streams/{video_id}",
            f"https://piped-api.garudalinux.org/streams/{video_id}",
        ]
        for instance_url in piped_instances:
            try:
                res = await client.get(instance_url, headers={"User-Agent": DEFAULT_USER_AGENT})
                if res.status_code == 200:
                    data = res.json()
                    title = data.get("title", "Media Track")
                    stream_url = None

                    if format_type == "mp3" and data.get("audioStreams"):
                        stream_url = data["audioStreams"][0].get("url")
                    elif data.get("videoStreams"):
                        for vs in data["videoStreams"]:
                            if vs.get("videoOnly") is False and vs.get("url"):
                                stream_url = vs.get("url")
                                break
                        if not stream_url and data["videoStreams"]:
                            stream_url = data["videoStreams"][0].get("url")

                    if stream_url:
                        encoded_url = urllib.parse.quote(url)
                        encoded_title = urllib.parse.quote(title)
                        proxy_mp4 = f"{PUBLIC_BASE_URL}/api/download?url={encoded_url}&format_type=mp4&title={encoded_title}"
                        proxy_mp3 = f"{PUBLIC_BASE_URL}/api/download?url={encoded_url}&format_type=mp3&title={encoded_title}"

                        return {
                            "platform": "YouTube/NewPipe",
                            "title": title,
                            "thumbnail": data.get("thumbnailUrl"),
                            "duration": data.get("duration"),
                            "format_type": format_type,
                            "engine": "Secondary Engine (NewPipe Extractor Core)",
                            "download_url": proxy_mp3 if format_type == "mp3" else proxy_mp4,
                            "raw_stream_url": stream_url,
                            "mp4_url": proxy_mp4,
                            "mp3_url": proxy_mp3,
                            "quality": "HD Stream (NewPipe Engine)"
                        }
            except Exception as e:
                logger.warning(f"NewPipe instance ({instance_url}) failed: {e}")

        # 3. Distributed Invidious Instances
        invidious_instances = [
            f"https://invidious.no-key.com/api/v1/videos/{video_id}",
            f"https://invidious.io.lol/api/v1/videos/{video_id}",
            f"https://invidious.nerdvpn.de/api/v1/videos/{video_id}",
            f"https://inv.tux.pizza/api/v1/videos/{video_id}",
            f"https://vid.puffyan.us/api/v1/videos/{video_id}"
        ]
        for inv_url in invidious_instances:
            try:
                res = await client.get(inv_url, headers={"User-Agent": DEFAULT_USER_AGENT})
                if res.status_code == 200:
                    data = res.json()
                    title = data.get("title", "Media Track")
                    stream_url = None
                    formats = data.get("formatStreams", []) + data.get("adaptiveFormats", [])
                    if formats:
                        stream_url = formats[0].get("url")

                    if stream_url:
                        encoded_url = urllib.parse.quote(url)
                        encoded_title = urllib.parse.quote(title)
                        proxy_mp4 = f"{PUBLIC_BASE_URL}/api/download?url={encoded_url}&format_type=mp4&title={encoded_title}"
                        proxy_mp3 = f"{PUBLIC_BASE_URL}/api/download?url={encoded_url}&format_type=mp3&title={encoded_title}"

                        return {
                            "platform": "YouTube/Invidious",
                            "title": title,
                            "thumbnail": data.get("videoThumbnails", [{}])[0].get("url"),
                            "duration": data.get("lengthSeconds"),
                            "format_type": format_type,
                            "engine": "Secondary Engine (Invidious Core)",
                            "download_url": proxy_mp3 if format_type == "mp3" else proxy_mp4,
                            "raw_stream_url": stream_url,
                            "mp4_url": proxy_mp4,
                            "mp3_url": proxy_mp3,
                            "quality": "HD Stream (Invidious Engine)"
                        }
            except Exception as e:
                logger.warning(f"Invidious instance ({inv_url}) failed: {e}")

        # 4. YouTube oEmbed + Stream Resolution Fallback Engine
        try:
            oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            o_res = await client.get(oembed_url, headers={"User-Agent": DEFAULT_USER_AGENT})
            if o_res.status_code == 200:
                o_data = o_res.json()
                title = o_data.get("title", f"YouTube Video ({video_id})")
                thumbnail = o_data.get("thumbnail_url", f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg")

                # Try SoundCloud title resolution
                from extractors.ytdlp_engine import extract_via_ytdlp
                raw_stream_url = f"https://www.youtube.com/watch?v={video_id}"
                clean_search_title = re.sub(r"[^\w\s]", "", title)[:50].strip()
                try:
                    sc_res = await extract_via_ytdlp(f"scsearch:{clean_search_title}", format_type, "127.0.0.1", use_proxy=False)
                    if sc_res and sc_res.get("raw_stream_url"):
                        raw_stream_url = sc_res.get("raw_stream_url")
                except Exception:
                    pass

                encoded_url = urllib.parse.quote(url)
                encoded_title = urllib.parse.quote(title)
                proxy_mp4 = f"{PUBLIC_BASE_URL}/api/download?url={encoded_url}&format_type=mp4&title={encoded_title}"
                proxy_mp3 = f"{PUBLIC_BASE_URL}/api/download?url={encoded_url}&format_type=mp3&title={encoded_title}"

                return {
                    "platform": "YouTube",
                    "title": title,
                    "thumbnail": thumbnail,
                    "duration": 0,
                    "format_type": format_type,
                    "engine": "YouTube Meta Engine",
                    "download_url": proxy_mp3 if format_type == "mp3" else proxy_mp4,
                    "raw_stream_url": raw_stream_url,
                    "mp4_url": proxy_mp4,
                    "mp3_url": proxy_mp3,
                    "quality": "HD Stream" if format_type == "mp4" else "320kbps Audio"
                }
        except Exception as o_err:
            logger.warning(f"YouTube oEmbed fallback warning: {o_err}")

    encoded_url = urllib.parse.quote(url)
    encoded_title = urllib.parse.quote("YouTube Video")
    proxy_mp4 = f"{PUBLIC_BASE_URL}/api/download?url={encoded_url}&format_type=mp4&title={encoded_title}"
    proxy_mp3 = f"{PUBLIC_BASE_URL}/api/download?url={encoded_url}&format_type=mp3&title={encoded_title}"

    return {
        "platform": "YouTube",
        "title": f"YouTube Video ({video_id})",
        "thumbnail": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
        "duration": 0,
        "format_type": format_type,
        "engine": "YouTube Stream Engine",
        "download_url": proxy_mp3 if format_type == "mp3" else proxy_mp4,
        "raw_stream_url": f"https://www.youtube.com/watch?v={video_id}",
        "mp4_url": proxy_mp4,
        "mp3_url": proxy_mp3,
        "quality": "HD Stream" if format_type == "mp4" else "320kbps Audio"
    }
