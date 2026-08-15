"""
Auto-rotating free HTTP proxy pool (no subscription, no user input).

Fetches public proxy lists from free sources, rotates on every request,
and retries with the next proxy when a download fails.
"""
from __future__ import annotations

import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

_lock = threading.Lock()
_proxies: list[str] = []
_bad: set[str] = set()
_round_robin_index = 0
_last_refresh_at = 0.0
_refreshing = False

_PROXY_LINE = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3}):(\d{1,5})$")

# Free public lists (no API key). Best-effort only.
_FREE_SOURCES = (
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=8000&country=all",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt",
)


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def auto_proxy_enabled() -> bool:
    """Default OFF: direct connection (faster). Set YT_DLP_AUTO_PROXY=true to enable free proxy pool."""
    return _env_bool("YT_DLP_AUTO_PROXY", False)


def _fallback_attempts() -> int:
    if auto_proxy_enabled():
        return 0
    try:
        return max(0, min(3, int(os.environ.get("YT_DLP_PROXY_FALLBACK_ATTEMPTS", "3"))))
    except ValueError:
        return 3


def fallback_pool_enabled() -> bool:
    """Allow proxy pool for limited retries after direct fails (even when AUTO_PROXY=false)."""
    return not auto_proxy_enabled() and _fallback_attempts() > 0


def _refresh_seconds() -> int:
    try:
        return max(60, int(os.environ.get("YT_DLP_PROXY_POOL_REFRESH_SECONDS", "600")))
    except ValueError:
        return 600


def _max_pool_size() -> int:
    try:
        return max(20, int(os.environ.get("YT_DLP_PROXY_POOL_MAX_SIZE", "120")))
    except ValueError:
        return 120


def _health_check_enabled() -> bool:
    return _env_bool("YT_DLP_PROXY_HEALTH_CHECK", False)


def _health_check_timeout() -> float:
    try:
        return max(1.0, min(8.0, float(os.environ.get("YT_DLP_PROXY_HEALTH_TIMEOUT_SEC", "3"))))
    except ValueError:
        return 3.0


def _health_check_url() -> str:
    return (os.environ.get("YT_DLP_PROXY_HEALTH_URL") or "https://www.instagram.com/").strip()


def _probe_proxy(proxy: str) -> bool:
    """Quick connectivity check before using a free proxy for yt-dlp."""
    if not _health_check_enabled():
        return True

    proxy_handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    opener = urllib.request.build_opener(proxy_handler)
    req = urllib.request.Request(
        _health_check_url(),
        headers={"User-Agent": "MixifyMediaImport/1.0"},
    )
    try:
        with opener.open(req, timeout=_health_check_timeout()) as resp:
            resp.read(256)
            return resp.status < 500
    except Exception:
        return False


def _next_live_proxy(max_scans: int = 6) -> str | None:
    """Round-robin next proxy that passes health check (if enabled)."""
    global _round_robin_index

    ensure_pool()

    with _lock:
        if not _proxies:
            return None
        pool_size = len(_proxies)
        scans = min(max_scans, pool_size * 2)

    for _ in range(scans):
        with _lock:
            proxy = _proxies[_round_robin_index % pool_size]
            _round_robin_index += 1
            if proxy in _bad:
                continue

        if _probe_proxy(proxy):
            return proxy

        mark_bad(proxy)
        print(f"[proxy-pool] health check failed: {proxy}", flush=True)

    with _lock:
        if _bad and len(_bad) >= pool_size:
            _bad.clear()
    return None


def _normalize_proxy(line: str) -> str | None:
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return None
    if "://" in raw:
        try:
            parsed = urlparse(raw)
            if parsed.scheme in ("http", "https") and parsed.hostname and parsed.port:
                return f"http://{parsed.hostname}:{parsed.port}"
        except Exception:
            return None
        return None
    match = _PROXY_LINE.match(raw)
    if not match:
        return None
    return f"http://{match.group(1)}:{match.group(2)}"


def _fetch_source(url: str, timeout: float = 12.0) -> list[str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "MixifyMediaImport/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[proxy-pool] source failed {url}: {e}", flush=True)
        return []

    out: list[str] = []
    for line in text.splitlines():
        proxy = _normalize_proxy(line)
        if proxy:
            out.append(proxy)
    return out


def refresh_pool(force: bool = False) -> int:
    """Download fresh free proxies. Returns pool size."""
    global _proxies, _bad, _last_refresh_at, _refreshing, _round_robin_index

    if not auto_proxy_enabled() and not fallback_pool_enabled():
        return 0

    now = time.time()
    with _lock:
        if _refreshing:
            return len(_proxies)
        if not force and _proxies and (now - _last_refresh_at) < _refresh_seconds():
            return len(_proxies)
        _refreshing = True

    collected: list[str] = []
    seen: set[str] = set()
    for source in _FREE_SOURCES:
        for proxy in _fetch_source(source):
            if proxy in seen:
                continue
            seen.add(proxy)
            collected.append(proxy)
            if len(collected) >= _max_pool_size():
                break
        if len(collected) >= _max_pool_size():
            break

    random.shuffle(collected)

    with _lock:
        if collected:
            _proxies = collected
            _bad.clear()
            _round_robin_index = 0
        _last_refresh_at = time.time()
        _refreshing = False
        size = len(_proxies)

    print(f"[proxy-pool] refreshed: {size} proxies", flush=True)
    return size


def ensure_pool() -> int:
    if not auto_proxy_enabled() and not fallback_pool_enabled():
        return 0
    with _lock:
        has_proxies = bool(_proxies)
        stale = (time.time() - _last_refresh_at) >= _refresh_seconds()
    if not has_proxies or stale:
        return refresh_pool(force=not has_proxies)
    return len(_proxies)


def next_proxy() -> str | None:
    """Next proxy for this request (round-robin). Refreshes pool if empty."""
    if not auto_proxy_enabled() and not fallback_pool_enabled():
        return None
    return _next_live_proxy()


def mark_bad(proxy: str | None) -> None:
    if not proxy:
        return
    with _lock:
        _bad.add(proxy)


def next_fallback_proxies(limit: int) -> list[str]:
    """Up to `limit` distinct health-checked proxies for post-direct fallback retries."""
    if limit <= 0:
        return []
    ensure_pool()
    out: list[str] = []
    seen: set[str] = set()
    for _ in range(limit * 8):
        proxy = next_proxy()
        if not proxy or proxy in seen:
            continue
        seen.add(proxy)
        out.append(proxy)
        if len(out) >= limit:
            break
    print(f"[proxy-pool] selected {len(out)}/{limit} fallback proxies", flush=True)
    return out


def pool_status() -> dict:
    with _lock:
        return {
            "auto_proxy_enabled": auto_proxy_enabled(),
            "fallback_pool_enabled": fallback_pool_enabled(),
            "proxy_pool_size": len(_proxies),
            "proxy_pool_bad": len(_bad),
            "proxy_health_check": _health_check_enabled(),
            "proxy_pool_last_refresh_sec_ago": (
                int(time.time() - _last_refresh_at) if _last_refresh_at else None
            ),
        }
