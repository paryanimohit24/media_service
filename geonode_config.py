"""Geonode residential proxy configuration for yt-dlp (optional)."""
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
    """Legacy flag: scraper API key present (scraping path removed; proxy may still be used)."""
    if not geonode_api_key():
        return False
    return _env_bool("GEONODE_ENABLED", True)


def geonode_allow_direct() -> bool:
    """When false, yt-dlp only uses configured proxy (no server IP)."""
    if geonode_proxy_url():
        return _env_bool("GEONODE_ALLOW_DIRECT", False)
    return _env_bool("GEONODE_ALLOW_DIRECT", True)


def geonode_max_attempts() -> int:
    try:
        return max(1, min(6, int(os.environ.get("GEONODE_MAX_ATTEMPTS", "3"))))
    except ValueError:
        return 3


def geonode_proxy_url() -> str | None:
    """
    HTTP proxy for yt-dlp (Geonode residential or any HTTP proxy).
    Set GEONODE_PROXY_URL or GEONODE_PROXY_USERNAME + GEONODE_PROXY_PASSWORD.
    """
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
        "import_strategy": "ytdlp_only",
        "geonode_scraper_enabled": geonode_enabled(),
        "geonode_api_key_set": bool(geonode_api_key()),
        "geonode_allow_direct": geonode_allow_direct(),
        "geonode_proxy_url_configured": bool(geonode_proxy_url()),
        "geonode_max_attempts": geonode_max_attempts(),
    }
