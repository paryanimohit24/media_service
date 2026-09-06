"""
Downloader Service Module
Handles multi-tier media stream downloading with cookies, rotating proxies,
and fallback pipelines for single downloads and multi-track merges.
"""

import os
import glob
import json
import logging
import subprocess
import asyncio
from typing import Optional, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor

import httpx
import yt_dlp

from config import (
    DEFAULT_USER_AGENT,
    FFMPEG_PATH,
    FFPROBE_PATH,
    FFMPEG_TIMEOUT_SECONDS,
    MAX_THREAD_WORKERS,
    get_cookie_file_for_url,
    get_random_proxy,
    mark_proxy_failed,
)

logger = logging.getLogger("DownloaderService")
download_thread_pool = ThreadPoolExecutor(max_workers=MAX_THREAD_WORKERS)


def build_platform_headers(url: str, client_ip: str = "127.0.0.1") -> Dict[str, str]:
    """Generates platform-specific HTTP headers (Referer, User-Agent)."""
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    url_lower = url.lower()
    if "tiktok" in url_lower or "tiktokcdn" in url_lower:
        headers["Referer"] = "https://www.tiktok.com/"
    elif "instagram" in url_lower or "cdninstagram" in url_lower:
        headers["Referer"] = "https://www.instagram.com/"
    elif "facebook" in url_lower or "fbcdn" in url_lower:
        headers["Referer"] = "https://www.facebook.com/"
    elif "reddit" in url_lower or "v.redd.it" in url_lower:
        headers["Referer"] = "https://www.reddit.com/"
    elif "pinterest" in url_lower or "pinimg" in url_lower:
        headers["Referer"] = "https://www.pinterest.com/"

    return headers


def sync_download_stream(
    target_url: str,
    raw_stream_url: str,
    is_video: bool,
    base_path: str,
    client_ip: str = "127.0.0.1"
) -> Optional[str]:
    """
    Synchronous multi-tier stream downloader:
    1. Direct yt-dlp on target_url (with cookies and client_ip)
    2. Proxy yt-dlp on target_url (up to 3 proxy retries)
    3. Direct httpx download of raw_stream_url (with platform Referer)
    4. FFmpeg stream download (handles HLS m3u8, AAC, MP3, DASH streams)
    Returns absolute path to the downloaded file, or None if failed.
    """
    fmt_type = "mp4" if is_video else "mp3"
    out_template = base_path + ".%(ext)s"

    cookie_file = get_cookie_file_for_url(target_url)
    ydl_opts: Dict[str, Any] = {
        "format": "bv*[height<=1080]+ba/b[height<=1080]/best" if is_video else "bestaudio/18/best",
        "outtmpl": out_template,
        "quiet": True,
        "no_warnings": True,
        "overwrites": True,
        "nocheckcertificate": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["android"]
            }
        },
        "http_headers": {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        }
    }
    if cookie_file and os.path.exists(cookie_file):
        ydl_opts["cookiefile"] = cookie_file

    # Tier 1: Direct yt-dlp (Priority for Video to ensure audio+video are properly merged/muxed, skip for spotify.com)
    if "spotify.com" not in target_url.lower():
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([target_url])
            valid = [f for f in glob.glob(base_path + ".*") if os.path.exists(f) and os.path.getsize(f) > 1000]
            if valid:
                return valid[0]
        except Exception as e:
            logger.debug(f"Direct yt-dlp download failed for {target_url[:60]}: {e}")

        # Tier 2: yt-dlp with rotating proxies
        for _ in range(3):
            proxy = get_random_proxy()
            if not proxy:
                break
            p_opts = ydl_opts.copy()
            p_opts["proxy"] = proxy
            try:
                with yt_dlp.YoutubeDL(p_opts) as ydl:
                    ydl.download([target_url])
                valid = [f for f in glob.glob(base_path + ".*") if os.path.exists(f) and os.path.getsize(f) > 1000]
                if valid:
                    return valid[0]
                else:
                    mark_proxy_failed(proxy)
            except Exception:
                mark_proxy_failed(proxy)

    # Fast Tier A: Direct Progressive Stream Download (MP3, MP4, AAC, etc.)
    is_hls_stream = any(k in (raw_stream_url or "").lower() for k in [".m3u8", "media-streaming", "playlist", "manifest"])
    is_direct_progressive = raw_stream_url and raw_stream_url.startswith("http") and not is_hls_stream and any(k in raw_stream_url.lower() for k in [".mp3", ".mp4", ".m4a", ".aac", ".ogg", ".wav", "sndcdn.com"])
    if is_direct_progressive:
        tmp_raw_file = base_path + (".mp4" if is_video else ".mp3")
        try:
            headers = build_platform_headers(raw_stream_url or target_url, client_ip)
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                with client.stream("GET", raw_stream_url, headers=headers) as resp:
                    if resp.status_code < 400:
                        with open(tmp_raw_file, "wb") as f:
                            for chunk in resp.iter_bytes(65536):
                                f.write(chunk)
            if os.path.exists(tmp_raw_file) and os.path.getsize(tmp_raw_file) > 1000:
                with open(tmp_raw_file, "rb") as f_chk:
                    head = f_chk.read(32)
                if not (head.startswith(b"#EXTM3U") or head.startswith(b"<html") or head.startswith(b"<!DOC")):
                    return tmp_raw_file
                else:
                    try:
                        os.remove(tmp_raw_file)
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"Direct progressive stream download notice: {e}")

    # Fast Tier B: Direct FFmpeg stream download for HLS/M3U8 streams (e.g. SoundCloud HLS for Spotify)
    if is_hls_stream and raw_stream_url and raw_stream_url.startswith("http"):
        tmp_ff_file = base_path + (".mp4" if is_video else ".mp3")
        headers = build_platform_headers(raw_stream_url or target_url, client_ip)
        ff_header_str = f"User-Agent: {DEFAULT_USER_AGENT}\r\n"
        if "Referer" in headers:
            ff_header_str += f"Referer: {headers['Referer']}\r\n"

        ff_cmd = [
            FFMPEG_PATH, "-y",
            "-headers", ff_header_str,
            "-i", raw_stream_url,
            "-c:v", "copy", "-c:a", "copy",
            tmp_ff_file
        ] if is_video else [
            FFMPEG_PATH, "-y",
            "-headers", ff_header_str,
            "-i", raw_stream_url,
            "-c:a", "libmp3lame", "-b:a", "320k", "-ar", "44100", "-ac", "2",
            tmp_ff_file
        ]
        try:
            r = subprocess.run(ff_cmd, capture_output=True, text=True, timeout=60)
            if os.path.exists(tmp_ff_file) and os.path.getsize(tmp_ff_file) > 1000:
                return tmp_ff_file
        except Exception as e:
            logger.debug(f"Fast HLS FFmpeg stream download notice for {raw_stream_url[:60]}: {e}")

    # Tier 3: Direct or Proxy httpx chunked download of raw_stream_url (fallback)
    if raw_stream_url and raw_stream_url.startswith("http") and not is_hls_stream:
        headers = build_platform_headers(raw_stream_url or target_url, client_ip)
        tmp_raw_file = base_path + (".mp4" if is_video else ".mp3")
        
        # 3a. Direct download
        try:
            with httpx.Client(timeout=45.0, follow_redirects=True) as client:
                with client.stream("GET", raw_stream_url, headers=headers) as resp:
                    if resp.status_code < 400:
                        with open(tmp_raw_file, "wb") as f:
                            for chunk in resp.iter_bytes(65536):
                                f.write(chunk)
            if os.path.exists(tmp_raw_file) and os.path.getsize(tmp_raw_file) > 1000:
                with open(tmp_raw_file, "rb") as f_chk:
                    head = f_chk.read(32)
                if not (head.startswith(b"#EXTM3U") or head.startswith(b"<html") or head.startswith(b"<!DOC")):
                    return tmp_raw_file
                else:
                    try:
                        os.remove(tmp_raw_file)
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"Direct httpx download failed for {raw_stream_url[:60]}: {e}")

        # 3b. Proxy download fallback
        for _ in range(2):
            proxy = get_random_proxy()
            if not proxy:
                break
            try:
                with httpx.Client(proxy=proxy, timeout=45.0, follow_redirects=True) as client:
                    with client.stream("GET", raw_stream_url, headers=headers) as resp:
                        if resp.status_code < 400:
                            with open(tmp_raw_file, "wb") as f:
                                for chunk in resp.iter_bytes(65536):
                                    f.write(chunk)
                if os.path.exists(tmp_raw_file) and os.path.getsize(tmp_raw_file) > 1000:
                    with open(tmp_raw_file, "rb") as f_chk:
                        head = f_chk.read(32)
                    if not (head.startswith(b"#EXTM3U") or head.startswith(b"<html") or head.startswith(b"<!DOC")):
                        return tmp_raw_file
                    else:
                        try:
                            os.remove(tmp_raw_file)
                        except Exception:
                            pass
            except Exception:
                continue

    # Tier 4: Direct FFmpeg stream download (fallback for remaining streams)
    if raw_stream_url and raw_stream_url.startswith("http"):
        tmp_ff_file = base_path + (".mp4" if is_video else ".mp3")
        headers = build_platform_headers(raw_stream_url or target_url, client_ip)
        ff_header_str = f"User-Agent: {DEFAULT_USER_AGENT}\r\n"
        if "Referer" in headers:
            ff_header_str += f"Referer: {headers['Referer']}\r\n"

        ff_cmd = [
            FFMPEG_PATH, "-y",
            "-headers", ff_header_str,
            "-i", raw_stream_url,
            "-c:v", "copy", "-c:a", "copy",
            tmp_ff_file
        ] if is_video else [
            FFMPEG_PATH, "-y",
            "-headers", ff_header_str,
            "-i", raw_stream_url,
            "-c:a", "libmp3lame", "-b:a", "320k", "-ar", "44100", "-ac", "2",
            tmp_ff_file
        ]
        try:
            subprocess.run(ff_cmd, capture_output=True, text=True, timeout=60)
            if os.path.exists(tmp_ff_file) and os.path.getsize(tmp_ff_file) > 1000:
                return tmp_ff_file
        except Exception as e:
            logger.debug(f"FFmpeg stream download failed for {raw_stream_url[:60]}: {e}")


    return None


async def download_media_async(
    target_url: str,
    raw_stream_url: str,
    is_video: bool,
    base_path: str,
    client_ip: str = "127.0.0.1"
) -> Optional[str]:
    """Asynchronous wrapper for sync_download_stream running inside thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        download_thread_pool,
        lambda: sync_download_stream(target_url, raw_stream_url, is_video, base_path, client_ip)
    )


def probe_and_normalize_for_playback(input_path: str, output_path: str, is_video: bool) -> str:
    """
    Probes downloaded media file.
    If video contains codecs incompatible with web browsers (e.g. VP9, AV1, or missing AAC audio),
    normalizes via FFmpeg to standard H.264 + AAC yuv420p.
    If audio is not standard MP3 (e.g. Opus, Ogg, AAC container), converts to universal MP3.
    Returns the path to the playback-ready file.
    """
    try:
        probe_cmd = [
            FFPROBE_PATH, "-v", "quiet", "-print_format", "json",
            "-show_streams", input_path
        ]
        res = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
        if res.stdout:
            data = json.loads(res.stdout)
            streams = data.get("streams", [])
            video_codec = next((s.get("codec_name", "").lower() for s in streams if s.get("codec_type") == "video"), "")
            audio_codec = next((s.get("codec_name", "").lower() for s in streams if s.get("codec_type") == "audio"), "")

            if is_video:
                # H.264 (avc1) + AAC is universally compatible across all browsers
                if video_codec in ["h264", "avc1"] and audio_codec in ["aac", "mp3"]:
                    return input_path

                logger.info(f"Normalizing video codecs ({video_codec}/{audio_codec}) to H.264 + AAC for playback compatibility...")
                norm_cmd = [
                    FFMPEG_PATH, "-y",
                    "-i", input_path,
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k",
                    output_path
                ]
                subprocess.run(norm_cmd, capture_output=True, text=True, timeout=120)
                if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                    return output_path
            else:
                # Audio: ensure valid MP3 codec for client playback
                if audio_codec == "mp3":
                    return input_path

                logger.info(f"Converting audio codec ({audio_codec}) to standard MP3...")
                norm_cmd = [
                    FFMPEG_PATH, "-y",
                    "-i", input_path,
                    "-vn", "-c:a", "libmp3lame", "-b:a", "320k",
                    output_path
                ]
                subprocess.run(norm_cmd, capture_output=True, text=True, timeout=60)
                if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                    return output_path
    except Exception as e:
        logger.warning(f"Codec probe/normalization fallback notice: {e}")

    return input_path
