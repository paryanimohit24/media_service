"""
Application Configuration Module
Centralizes all environment variables, path resolutions, and resource limits.
"""

import os
import sys
import tempfile
from typing import List

# Base Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_DIR = os.path.join(BASE_DIR, "cookies")
COOKIES_PATH = os.path.join(BASE_DIR, "cookies.txt")

# Server & Public URLs
PORT = int(os.getenv("PORT", 8001))
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")


def build_proxy_download_url(page_url: str, format_type: str, title: str) -> str:
    """Relative /api/download path when PUBLIC_BASE_URL is unset (behind Spring proxy)."""
    import urllib.parse

    encoded_url = urllib.parse.quote(page_url)
    encoded_title = urllib.parse.quote(title or "media")
    path = f"/api/download?url={encoded_url}&format_type={format_type}&title={encoded_title}"
    return f"{PUBLIC_BASE_URL}{path}" if PUBLIC_BASE_URL else path

# Custom Temporary Directory (Crucial for systems where C: drive has limited space)
_env_temp_dir = os.getenv("TEMP_DIR", "").strip()
if _env_temp_dir:
    TEMP_DIR = _env_temp_dir
else:
    # Auto-detect project-local tmp directory if on Windows with D: drive setup
    project_tmp = os.path.join(os.path.dirname(BASE_DIR), "tmp")
    if os.path.exists(project_tmp) or os.name == "nt":
        TEMP_DIR = project_tmp
    else:
        TEMP_DIR = tempfile.gettempdir()

os.makedirs(TEMP_DIR, exist_ok=True)
os.environ["TEMP"] = TEMP_DIR
os.environ["TMP"] = TEMP_DIR
tempfile.tempdir = TEMP_DIR

# FFmpeg & FFprobe Binary Resolution
# Priority: 1. ENV vars, 2. Local binaries in BASE_DIR, 3. System PATH
_env_ffmpeg = os.getenv("FFMPEG_PATH", "").strip()
if _env_ffmpeg and os.path.exists(_env_ffmpeg):
    FFMPEG_PATH = _env_ffmpeg
elif os.path.exists(os.path.join(BASE_DIR, "ffmpeg.exe")):
    FFMPEG_PATH = os.path.join(BASE_DIR, "ffmpeg.exe")
elif os.path.exists(os.path.join(BASE_DIR, "ffmpeg")):
    FFMPEG_PATH = os.path.join(BASE_DIR, "ffmpeg")
else:
    FFMPEG_PATH = "ffmpeg"

_env_ffprobe = os.getenv("FFPROBE_PATH", "").strip()
if _env_ffprobe and os.path.exists(_env_ffprobe):
    FFPROBE_PATH = _env_ffprobe
elif os.path.exists(os.path.join(BASE_DIR, "ffprobe.exe")):
    FFPROBE_PATH = os.path.join(BASE_DIR, "ffprobe.exe")
elif os.path.exists(os.path.join(BASE_DIR, "ffprobe")):
    FFPROBE_PATH = os.path.join(BASE_DIR, "ffprobe")
else:
    FFPROBE_PATH = "ffprobe"

# Ensure local binary directory is in PATH for child subprocesses
if BASE_DIR not in os.environ.get("PATH", ""):
    os.environ["PATH"] = BASE_DIR + os.pathsep + os.environ.get("PATH", "")

# Concurrency & Resource Limits
MAX_CONCURRENT_FFMPEG = int(os.getenv("MAX_CONCURRENT_FFMPEG", 5))
FFMPEG_TIMEOUT_SECONDS = float(os.getenv("FFMPEG_TIMEOUT_SECONDS", 300.0))
MAX_THREAD_WORKERS = int(os.getenv("MAX_THREAD_WORKERS", 50))
MAX_HTTP_CONNECTIONS = int(os.getenv("MAX_HTTP_CONNECTIONS", 1000))
HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", 30.0))
MAX_MEDIA_DURATION_SECONDS = int(os.getenv("MAX_MEDIA_DURATION_SECONDS", 3600))
TEMP_FILE_MAX_AGE_SECONDS = int(os.getenv("TEMP_FILE_MAX_AGE_SECONDS", 1800))
MAX_FILE_SIZE_BYTES = int(os.getenv("MAX_FILE_SIZE_BYTES", 500 * 1024 * 1024))
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", 40))

# CORS & Security Settings
CORS_ORIGINS: List[str] = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# Re-export cookie and proxy service functions for backward compatibility
from services.cookie_service import get_cookie_file_for_url, PLATFORM_COOKIE_MAP as PLATFORM_COOKIES
from services.proxy_service import get_random_proxy, mark_proxy_failed, get_all_proxies, DEFAULT_PROXIES as PROXIES
