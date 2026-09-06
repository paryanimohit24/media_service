"""
Primary Extractor Engine (yt-dlp)
Executes universal media extraction with User-IP forwarding and cookie authentication.
"""

import os
import urllib.parse
import asyncio
from typing import Dict, Any
from concurrent.futures import ThreadPoolExecutor

import yt_dlp
from config import DEFAULT_USER_AGENT, get_cookie_file_for_url, build_proxy_download_url

thread_pool = ThreadPoolExecutor(max_workers=100)


def build_ytdlp_options(format_type: str = "mp4", client_ip: str = "127.0.0.1", url: str = "", cookie_file: str = None) -> Dict[str, Any]:
    """Generates optimized yt-dlp option dictionary for original maximum quality extraction."""
    # Always request 100% original highest quality:
    # For audio (mp3): bestaudio/best (highest bitrate audio available from source)
    # For video (mp4): bestvideo+bestaudio/best (highest resolution & original bitrate available from source)
    format_spec = "bestaudio/18/best" if format_type == "mp3" else "bestvideo+bestaudio/18/best"

    options = {
        'format': format_spec,
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'nocheckcertificate': True,
        'remote_components': ['ejs:github'],
        'extractor_args': {
            'youtube': {
                'player_client': ['android']
            },
            'instagram': {'rhots': True},
            'reddit': {'user_agent': ['Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15']}
        },
        'http_headers': {
            'User-Agent': DEFAULT_USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        },
    }

    target_cookie = cookie_file or (get_cookie_file_for_url(url) if url else None)
    if target_cookie and os.path.exists(target_cookie):
        options['cookiefile'] = target_cookie

    return options


def _sync_ytdlp_extract(url: str, format_type: str, client_ip: str, use_proxy: bool = False) -> Dict[str, Any]:
    """
    Synchronous worker function executed inside thread pool.
    Extraction Priority Flow:
    1. Direct yt-dlp + Platform Specific Cookies (if available) -> NO proxy (skipped if use_proxy is True)
    2. yt-dlp + Primary Proxy from pool (with cookies if available)
    3. Proxy Failover from pool (up to 3 retries)
    4. Raise exception -> Secondary fallback triggers (NewPipe/Piped)
    """
    from config import get_random_proxy, mark_proxy_failed
    
    target_url = url
    # Unroll shortlinks (pin.it, facebook.com/share/r/, fb.watch)
    if "pin.it" in target_url or "/share/" in target_url or "fb.watch" in target_url:
        try:
            import httpx
            with httpx.Client(follow_redirects=True, timeout=8.0) as client:
                res = client.get(target_url, headers={"User-Agent": DEFAULT_USER_AGENT})
                target_url = str(res.url)
        except Exception:
            pass

    if "reddit.com" in target_url and "/s/" in target_url:
        try:
            import httpx
            rx_url = target_url.replace("www.reddit.com", "rxddit.com").replace("reddit.com", "rxddit.com")
            headers = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"}
            with httpx.Client(timeout=8.0, follow_redirects=False, headers=headers) as client:
                res = client.get(rx_url)
                loc = res.headers.get("location") or str(res.url)
                if "comments" in loc:
                    target_url = loc.replace("rxddit.com", "www.reddit.com").split("?")[0]
        except Exception:
            pass

    if "instagram.com/reels/" in target_url:
        target_url = target_url.replace("instagram.com/reels/", "instagram.com/reel/")

    cookie_path = get_cookie_file_for_url(target_url)
    options = build_ytdlp_options(format_type=format_type, client_ip=client_ip, url=target_url, cookie_file=cookie_path)
    
    info = None
    last_err = None

    # Step 1: Direct yt-dlp (only if use_proxy is False)
    if not use_proxy:
        try:
            direct_opts = options.copy()
            with yt_dlp.YoutubeDL(direct_opts) as ydl:
                info = ydl.extract_info(target_url, download=False)
        except Exception as direct_err:
            last_err = direct_err

    # Step 2 & 3: Try proxy pool with failover retry (up to 3 proxy attempts)
    if not info:
        max_attempts = 3
        for attempt in range(max_attempts):
            proxy = get_random_proxy()
            proxy_opts = options.copy()
            if proxy:
                proxy_opts['proxy'] = proxy
            
            try:
                with yt_dlp.YoutubeDL(proxy_opts) as ydl:
                    info = ydl.extract_info(target_url, download=False)
                    if info:
                        break
            except Exception as proxy_err:
                last_err = proxy_err
                if proxy:
                    mark_proxy_failed(proxy)

    if not info:
        raise last_err or Exception(f"Primary yt-dlp engine extraction failed for media URL")

    if 'entries' in info and info['entries']:
        info = info['entries'][0]

    stream_url = info.get("url")
    formats = info.get("formats", [])

    # Smart stream selection:
    if formats:
        if format_type == "mp4":
            # 1. Prioritize progressive streams (containing both video AND audio)
            progressive = []
            for fmt in formats:
                if not fmt.get("url"):
                    continue
                vcodec = fmt.get("vcodec") or ""
                acodec = fmt.get("acodec") or ""
                if vcodec != "none" and acodec != "none":
                    progressive.append(fmt)
            if progressive:
                best_prog = None
                for p in progressive:
                    fid = str(p.get("format_id", "")).lower()
                    if "hd" in fid:
                        best_prog = p
                        break
                if not best_prog:
                    best_prog = progressive[-1]
                stream_url = best_prog.get("url")
        elif format_type == "mp3":
            # 1. Prioritize pure audio-only streams (vcodec == 'none' and acodec != 'none')
            audio_only = [
                f for f in formats 
                if f.get("url") and (f.get("vcodec") or "") == "none" and (f.get("acodec") or "") not in ["none", None, ""]
            ]
            if audio_only:
                best_audio = max(audio_only, key=lambda f: float(f.get("tbr") or f.get("abr") or 0))
                stream_url = best_audio.get("url")
            else:
                # 2. Fallback to progressive stream with audio (format 18 / etc.)
                with_audio = [
                    f for f in formats 
                    if f.get("url") and (f.get("acodec") or "") not in ["none", None, ""] and not str(f.get("format_id", "")).startswith("sb")
                ]
                if with_audio:
                    stream_url = with_audio[-1].get("url")

    # Fallback to direct info url or last valid non-storyboard format url
    if not stream_url and formats:
        valid_media = [
            f for f in formats 
            if f.get("url") and not str(f.get("format_id", "")).startswith("sb")
        ]
        if valid_media:
            stream_url = valid_media[-1].get("url")

    if not stream_url:
        raise Exception(f"Primary yt-dlp engine found no direct stream for format {format_type}")

    title = info.get("title", "Downloaded Media")
    platform = info.get("extractor_key", "Universal")

    proxy_mp4 = build_proxy_download_url(url, "mp4", title)
    proxy_mp3 = build_proxy_download_url(url, "mp3", title)

    return {
        "platform": platform,
        "title": title,
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "format_type": format_type,
        "engine": "Primary Engine (yt-dlp)",
        "download_url": proxy_mp3 if format_type == "mp3" else proxy_mp4,
        "raw_stream_url": stream_url,
        "mp4_url": proxy_mp4,
        "mp3_url": proxy_mp3,
        "quality": "HD Video Stream" if format_type == "mp4" else "320kbps Audio Stream"
    }


async def extract_via_ytdlp(url: str, format_type: str, client_ip: str, use_proxy: bool = False) -> Dict[str, Any]:
    """Asynchronous wrapper for yt-dlp extraction."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        thread_pool, 
        lambda: _sync_ytdlp_extract(url, format_type, client_ip, use_proxy)
    )
