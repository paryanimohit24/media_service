"""Backward-compatible /import-audio pipeline using the demo extraction engine."""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass

from extractors.dispatcher import process_media_extraction
from services.downloader_service import sync_download_stream, probe_and_normalize_for_playback

BYTES_DOWNLOADED_HEADER = "X-Import-Bytes-Downloaded"
AUDIO_SIZE_HEADER = "X-Import-Audio-Size-Bytes"
DOWNLOAD_MODE_HEADER = "X-Import-Download-Mode"

_INSTAGRAM_URL = re.compile(
    r"^https?://(www\.)?(instagram\.com|instagr\.am)/(reel|reels|p|tv)/[\w-]+/?.*$",
    re.IGNORECASE,
)
_YOUTUBE_URL = re.compile(
    r"^https?://((www\.|m\.)?youtube\.com/(watch\?v=|shorts/|embed/|live/)|music\.youtube\.com/|youtu\.be/)[^?#]+.*$",
    re.IGNORECASE,
)
_TIKTOK_URL = re.compile(
    r"^https?://([\w-]+\.)*tiktok\.com/[^?#\s]+.*$",
    re.IGNORECASE,
)
_SNAPCHAT_URL = re.compile(
    r"^https?://((www\.|t\.)?snapchat\.com|story\.snapchat\.com)/[^?#]+.*$",
    re.IGNORECASE,
)
_FACEBOOK_URL = re.compile(
    r"^https?://((www\.|m\.)?facebook\.com/(watch|reel|reels|videos|share|r|video)/|fb\.watch/)[^?#]+.*$",
    re.IGNORECASE,
)
_PINTEREST_URL = re.compile(
    r"^https?://((www\.|m\.)?pinterest\.com/|pin\.it/)[^?#\s]+.*$",
    re.IGNORECASE,
)
_REDDIT_URL = re.compile(
    r"^https?://((www\.|old\.|m\.|np\.)?reddit\.com/|redd\.it/)[^?#\s]+.*$",
    re.IGNORECASE,
)

SUPPORTED_URLS_MESSAGE = (
    "Unsupported URL. Paste a public Instagram, YouTube, TikTok, Snapchat, "
    "Facebook, Pinterest, or Reddit link."
)


@dataclass(frozen=True)
class ImportAudioResult:
    data: bytes
    filename: str
    media_type: str
    bytes_downloaded: int
    audio_size_bytes: int
    download_mode: str


def is_supported_url(url: str) -> bool:
    trimmed = (url or "").strip()
    if not trimmed:
        return False
    return bool(
        _INSTAGRAM_URL.match(trimmed)
        or _YOUTUBE_URL.match(trimmed)
        or _TIKTOK_URL.match(trimmed)
        or _SNAPCHAT_URL.match(trimmed)
        or _FACEBOOK_URL.match(trimmed)
        or _PINTEREST_URL.match(trimmed)
        or _REDDIT_URL.match(trimmed)
    )


def _safe_filename(title: str, ext: str) -> str:
    base = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")
    if not base:
        base = "imported_audio"
    if len(base) > 80:
        base = base[:80]
    return f"{base}.{ext}"


def _guess_download_mode(path: str, raw_stream_url: str) -> str:
    lower = (path or "").lower()
    raw_lower = (raw_stream_url or "").lower()
    if any(token in lower for token in (".mp3", ".m4a", ".aac", ".opus", ".ogg", ".wav")):
        return "audio_only"
    if any(token in raw_lower for token in (".mp3", ".m4a", "audio", "bestaudio")):
        return "audio_only"
    return "video_audio_processed"


def import_audio_from_url(url: str, client_ip: str = "127.0.0.1") -> ImportAudioResult:
    import asyncio

    async def _extract():
        return await process_media_extraction(url, format_type="mp3", client_ip=client_ip)

    extraction = asyncio.run(_extract())
    payload = extraction.get("data") or {}
    raw_stream_url = payload.get("raw_stream_url") or payload.get("download_url") or ""
    title = payload.get("title") or "imported_audio"

    with tempfile.TemporaryDirectory() as tmpdir:
        base_path = os.path.join(tmpdir, "import")
        downloaded = sync_download_stream(
            target_url=url,
            raw_stream_url=raw_stream_url,
            is_video=False,
            base_path=base_path,
            client_ip=client_ip,
        )
        if not downloaded or not os.path.exists(downloaded) or os.path.getsize(downloaded) < 500:
            raise RuntimeError("Could not download audio from this link.")

        final_path = downloaded
        ext = os.path.splitext(downloaded)[1].lstrip(".").lower() or "mp3"
        if ext not in {"mp3", "m4a", "aac"}:
            normalized = os.path.join(tmpdir, "import_normalized.mp3")
            final_path = probe_and_normalize_for_playback(downloaded, normalized, is_video=False)
            ext = "mp3"

        with open(final_path, "rb") as handle:
            data = handle.read()
        if not data:
            raise RuntimeError("Downloaded audio file is empty.")

        bytes_downloaded = os.path.getsize(downloaded)
        audio_size = len(data)
        download_mode = _guess_download_mode(downloaded, raw_stream_url)
        media_type = "audio/mp4" if ext == "m4a" else "audio/mpeg" if ext == "mp3" else "application/octet-stream"
        filename = _safe_filename(title, ext)

        return ImportAudioResult(
            data=data,
            filename=filename,
            media_type=media_type,
            bytes_downloaded=bytes_downloaded,
            audio_size_bytes=audio_size,
            download_mode=download_mode,
        )
