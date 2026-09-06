"""
Proxy Service Module
Handles proxy pool management, health tracking, and failover rotation.
"""

import os
import random
import logging
from typing import List, Optional, Set

logger = logging.getLogger("ProxyService")

def _load_proxies_from_env() -> List[str]:
    """Load proxy URLs from PROXIES env (comma-separated). Never hardcode credentials in git."""
    raw = os.getenv("PROXIES", "").strip()
    if not raw:
        return []
    return [
        p.strip()
        for p in raw.split(",")
        if p.strip() and p.strip().lower() not in ("none", "empty", "false", "0")
    ]


DEFAULT_PROXIES: List[str] = _load_proxies_from_env()

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
