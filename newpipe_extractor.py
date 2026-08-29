"""YouTube import via NewPipe Extractor Java CLI (test alternative to yt-dlp)."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

from media_download import media_to_m4a


@dataclass(frozen=True)
class NewPipeExtractResult:
    title: str
    media_url: str
    audio_only: bool


def newpipe_enabled() -> bool:
    raw = (os.environ.get("USE_NEWPIPE_EXTRACTOR") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def newpipe_jar_path() -> str:
    return (os.environ.get("NEWPIPE_CLI_JAR") or "/app/newpipe-cli.jar").strip()


def extract_stream_info(url: str, timeout_sec: int = 120) -> NewPipeExtractResult:
    jar = newpipe_jar_path()
    if not os.path.isfile(jar):
        raise RuntimeError(f"NewPipe CLI jar not found at {jar}")

    proc = subprocess.run(
        ["java", "-jar", jar, url.strip()],
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail or "NewPipe extractor failed.")

    try:
        payload = json.loads(proc.stdout.strip())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"NewPipe returned invalid JSON: {proc.stdout[:200]}") from e

    title = str(payload.get("title") or "imported_audio")
    media_url = str(payload.get("media_url") or "").strip()
    if not media_url.startswith("http"):
        raise RuntimeError("NewPipe did not return a media URL.")

    audio_only = bool(payload.get("audio_only", True))
    return NewPipeExtractResult(title=title, media_url=media_url, audio_only=audio_only)


def import_youtube_via_newpipe(url: str, tmpdir: str) -> tuple[str, str, int, int, str]:
    """Return (audio_path, title, bytes_downloaded, audio_size_bytes, download_mode)."""
    info = extract_stream_info(url)
    print(
        f"[media-import] newpipe resolved title={info.title!r} audio_only={info.audio_only}",
        flush=True,
    )

    referer = url if "youtube" in url.lower() or "youtu.be" in url.lower() else None
    audio_path, bytes_downloaded, download_mode = media_to_m4a(
        info.media_url,
        tmpdir,
        proxy=None,
        referer=referer or "https://www.youtube.com/",
    )
    audio_size = os.path.getsize(audio_path)
    if audio_size <= 0:
        raise RuntimeError("NewPipe download produced an empty audio file.")

    return audio_path, info.title, bytes_downloaded, audio_size, download_mode
