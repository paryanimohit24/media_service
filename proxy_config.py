"""Proxy selection: Geonode (paid) OR manual override OR legacy free pool."""
from __future__ import annotations

import os
import random
import threading
from urllib.parse import urlparse

from free_proxy_pool import auto_proxy_enabled, mark_bad, next_fallback_proxies, pool_status, refresh_pool
from geonode_config import geonode_enabled, geonode_status

_lock = threading.Lock()
_manual_round_robin_index = 0


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _split_proxy_list(raw: str) -> list[str]:
    items: list[str] = []
    for part in raw.replace("\n", ",").split(","):
        proxy = _clean(part)
        if proxy:
            items.append(proxy)
    return items


def _manual_proxy_configured() -> bool:
    if _clean(os.environ.get("YT_DLP_PROXY")):
        return True
    if _split_proxy_list(os.environ.get("YT_DLP_PROXY_LIST", "")):
        return True
    if _clean(os.environ.get("HTTPS_PROXY")) or _clean(os.environ.get("HTTP_PROXY")):
        return True
    return False


def manual_proxy_configured() -> bool:
    return _manual_proxy_configured()


def get_manual_proxy() -> str | None:
    single = _clean(os.environ.get("YT_DLP_PROXY"))
    if single:
        return single

    proxy_list = _split_proxy_list(os.environ.get("YT_DLP_PROXY_LIST", ""))
    if proxy_list:
        mode = (_clean(os.environ.get("YT_DLP_PROXY_ROTATION")) or "round_robin").lower()
        if mode == "random":
            return random.choice(proxy_list)
        global _manual_round_robin_index
        with _lock:
            proxy = proxy_list[_manual_round_robin_index % len(proxy_list)]
            _manual_round_robin_index += 1
            return proxy

    return _clean(os.environ.get("HTTPS_PROXY")) or _clean(os.environ.get("HTTP_PROXY"))


def use_free_proxy_pool() -> bool:
    """Free public proxy pool — disabled when Geonode Scraper API is active."""
    if geonode_enabled():
        return False
    return auto_proxy_enabled() or proxy_fallback_attempts() > 0


def get_proxy_url() -> str | None:
    manual = get_manual_proxy()
    if manual:
        return manual
    if auto_proxy_enabled():
        from free_proxy_pool import next_proxy

        return next_proxy()
    return None


def report_proxy_failure(proxy: str | None) -> None:
    if not proxy or geonode_enabled():
        return
    if _manual_proxy_configured():
        return
    mark_bad(proxy)


def max_attempts() -> int:
    try:
        return max(1, min(12, int(os.environ.get("YT_DLP_PROXY_MAX_ATTEMPTS", "6"))))
    except ValueError:
        return 6


def allow_direct_fallback() -> bool:
    return _env_bool("YT_DLP_ALLOW_DIRECT_FALLBACK", True)


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def mask_proxy(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "?"
        port = f":{parsed.port}" if parsed.port else ""
        scheme = parsed.scheme or "http"
        if parsed.username:
            return f"{scheme}://***:***@{host}{port}"
        return f"{scheme}://{host}{port}"
    except Exception:
        return "***"


def proxy_status() -> dict:
    if geonode_enabled():
        mode = "geonode_scraper"
    elif _manual_proxy_configured():
        mode = "manual"
    elif auto_proxy_enabled():
        mode = "auto_free_rotate"
    else:
        mode = "direct"

    status = {
        "proxy_enabled": geonode_enabled() or _manual_proxy_configured() or auto_proxy_enabled(),
        "proxy_mode": mode,
        "proxy_max_attempts_per_request": max_attempts(),
        "proxy_direct_fallback": allow_direct_fallback(),
        "proxy_fallback_attempts": proxy_fallback_attempts(),
        **geonode_status(),
    }
    if use_free_proxy_pool():
        status.update(pool_status())
    return status


def warm_pool() -> int:
    if geonode_enabled() or not use_free_proxy_pool():
        return 0
    return refresh_pool(force=True)


def direct_only() -> bool:
    return not _manual_proxy_configured() and not auto_proxy_enabled() and not geonode_enabled()


def proxy_fallback_attempts() -> int:
    if geonode_enabled() or not direct_only():
        return 0
    try:
        return max(0, min(3, int(os.environ.get("YT_DLP_PROXY_FALLBACK_ATTEMPTS", "3"))))
    except ValueError:
        return 3


def next_fallback_proxies_list(limit: int) -> list[str]:
    if not use_free_proxy_pool():
        return []
    return next_fallback_proxies(limit)
