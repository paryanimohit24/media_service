"""
Proxy Service Module
Handles proxy pool management, health tracking, and failover rotation.
"""

import os
import random
import logging
from typing import List, Optional, Set

logger = logging.getLogger("ProxyService")

# Load proxies from environment variable PROXIES (comma-separated, or 'none' for direct connection)
_env_proxies_raw = os.getenv("PROXIES")
if _env_proxies_raw is not None:
    DEFAULT_PROXIES: List[str] = [
        p.strip() for p in _env_proxies_raw.split(",")
        if p.strip() and p.strip().lower() not in ["none", "empty", "false", "0"]
    ]
else:
    # Production proxy fallbacks (Webshare rotating proxies)
    DEFAULT_PROXIES: List[str] = [
        "http://mrwxxodt:cjswosamlgqz@31.59.20.176:6754",
        "http://mrwxxodt:cjswosamlgqz@45.38.107.97:6014",
        "http://mrwxxodt:cjswosamlgqz@198.105.121.200:6462",
        "http://mrwxxodt:cjswosamlgqz@64.137.96.74:6641",
        "http://mrwxxodt:cjswosamlgqz@198.23.243.226:6361",
        "http://mrwxxodt:cjswosamlgqz@38.154.185.97:6370",
        "http://mrwxxodt:cjswosamlgqz@84.247.60.125:6095",
        "http://mrwxxodt:cjswosamlgqz@191.96.254.138:6185",
        "http://mrwxxodt:cjswosamlgqz@31.58.9.4:6077",
    ]

_failed_proxies: Set[str] = set()


def get_all_proxies() -> List[str]:
    """Returns the full list of configured proxies."""
    return list(DEFAULT_PROXIES)


def get_random_proxy() -> Optional[str]:
    """
    Returns a healthy proxy from the active proxy pool.
    If all proxies have failed, resets the failed set and retries.
    """
    if not DEFAULT_PROXIES:
        return None

    available = [p for p in DEFAULT_PROXIES if p not in _failed_proxies]
    if not available:
        logger.info("All proxies marked failed; resetting failed proxy pool.")
        _failed_proxies.clear()
        available = DEFAULT_PROXIES

    return random.choice(available)


def mark_proxy_failed(proxy_url: str) -> None:
    """Marks a proxy as temporarily failing to exclude it from rotation."""
    if proxy_url:
        _failed_proxies.add(proxy_url)
        logger.debug(f"Proxy marked failed. Total failed: {len(_failed_proxies)}")


def reset_failed_proxies() -> None:
    """Clears the failed proxy set."""
    _failed_proxies.clear()
