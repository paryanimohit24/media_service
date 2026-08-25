"""Download media and extract audio with ffmpeg."""
from __future__ import annotations

import os
import shutil
import subprocess
import urllib.request
from urllib.parse import urlparse

MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


def _guess_extension(media_url: str) -> str:
    path = urlparse(media_url).path.lower()
    for ext in (".m4a", ".mp3", ".mp4", ".webm", ".mov"):
        if path.endswith(ext):
            return ext.lstrip(".")
    if ".mp4" in media_url.lower():
        return "mp4"
    return "bin"


def is_probably_audio_url(media_url: str) -> bool:
    lower = media_url.lower()
    return any(x in lower for x in (".m4a", ".mp3", "mime=audio", "/audio"))


def download_media(
    media_url: str,
    dest_path: str,
    proxy: str | None = None,
    referer: str | None = None,
) -> str:
    headers = {"User-Agent": MOBILE_UA}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(media_url, headers=headers)
    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
        resp_ctx = opener.open(req, timeout=45)
    else:
        resp_ctx = urllib.request.urlopen(req, timeout=45)

    with resp_ctx as resp:
        if resp.status and resp.status >= 400:
            raise RuntimeError(f"Media download failed (HTTP {resp.status}).")

        total = 0
        with open(dest_path, "wb") as out:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise RuntimeError("Media file too large to download.")
                out.write(chunk)

    if not os.path.isfile(dest_path) or os.path.getsize(dest_path) < 800:
        raise RuntimeError("Downloaded media file is empty.")

    return dest_path


def extract_audio_to_m4a(input_path: str, output_m4a: str) -> str:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not available.")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vn",
        "-acodec",
        "aac",
        "-b:a",
        "192k",
        output_m4a,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-400:]
        raise RuntimeError(f"ffmpeg audio extraction failed: {tail}")

    if not os.path.isfile(output_m4a) or os.path.getsize(output_m4a) < 800:
        raise RuntimeError("ffmpeg produced an empty audio file.")

    return output_m4a


def media_to_m4a(
    media_url: str,
    tmpdir: str,
    proxy: str | None = None,
    referer: str | None = None,
) -> str:
    ext = _guess_extension(media_url)
    media_path = os.path.join(tmpdir, f"media.{ext}")
    download_media(media_url, media_path, proxy=proxy, referer=referer)

    if is_probably_audio_url(media_url) or ext in ("m4a", "mp3"):
        if ext == "m4a":
            return media_path
        out_m4a = os.path.join(tmpdir, "import.m4a")
        return extract_audio_to_m4a(media_path, out_m4a)

    out_m4a = os.path.join(tmpdir, "import.m4a")
    return extract_audio_to_m4a(media_path, out_m4a)
