"""Geonode Scraper API + optional HTTP proxy for yt-dlp."""
from __future__ import annotations

import os


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _env_bool(name: str, default: bool) -> bool:
    raw = (_clean(os.environ.get(name)) or "").lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def geonode_api_key() -> str | None:
    return _clean(os.environ.get("GEONODE_API_KEY"))


def geonode_enabled() -> bool:
    if not geonode_api_key():
        return False
    return _env_bool("GEONODE_ENABLED", True)


def geonode_extract_url() -> str:
    return _clean(os.environ.get("GEONODE_EXTRACT_URL")) or "https://scraper.geonode.io/v1/extract"


def geonode_render_js() -> bool:
    return _env_bool("GEONODE_RENDER_JS", True)


def geonode_processing_mode() -> str:
    mode = (_clean(os.environ.get("GEONODE_PROCESSING_MODE")) or "async").lower()
    if mode not in ("sync", "async"):
        return "async"
    return mode


def geonode_proxy_country() -> str | None:
    return _clean(os.environ.get("GEONODE_PROXY_COUNTRY"))


def geonode_proxy_type() -> str:
    return (_clean(os.environ.get("GEONODE_PROXY_TYPE")) or "residential").lower()


def geonode_poll_interval_sec() -> float:
    try:
        return max(2.0, min(15.0, float(os.environ.get("GEONODE_POLL_INTERVAL_SEC", "5"))))
    except ValueError:
        return 5.0


def geonode_poll_timeout_sec() -> float:
    try:
        return max(30.0, min(300.0, float(os.environ.get("GEONODE_POLL_TIMEOUT_SEC", "180"))))
    except ValueError:
        return 180.0


def geonode_allow_direct() -> bool:
    if geonode_proxy_url():
        return _env_bool("GEONODE_ALLOW_DIRECT", False)
    return _env_bool("GEONODE_ALLOW_DIRECT", True)


def geonode_max_attempts() -> int:
    try:
        return max(1, min(6, int(os.environ.get("GEONODE_MAX_ATTEMPTS", "3"))))
    except ValueError:
        return 3


def geonode_proxy_url() -> str | None:
    direct = _clean(os.environ.get("GEONODE_PROXY_URL"))
    if direct:
        return direct

    username = _clean(os.environ.get("GEONODE_PROXY_USERNAME"))
    password = _clean(os.environ.get("GEONODE_PROXY_PASSWORD"))
    if not username or not password:
        return None

    host = _clean(os.environ.get("GEONODE_PROXY_HOST")) or "proxy.geonode.io"
    port = _clean(os.environ.get("GEONODE_PROXY_PORT")) or "9000"
    return f"http://{username}:{password}@{host}:{port}"


def mobile_user_agent() -> str:
    return (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    )


def geonode_status() -> dict:
    return {
        "import_strategy": "instagram_ytdlp_others_page_extract",
        "geonode_scraper_enabled": geonode_enabled(),
        "geonode_api_key_set": bool(geonode_api_key()),
        "geonode_allow_direct": geonode_allow_direct(),
        "geonode_proxy_url_configured": bool(geonode_proxy_url()),
        "geonode_max_attempts": geonode_max_attempts(),
    }
