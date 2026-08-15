"""Geonode Scraper API client — residential proxy page extraction."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from geonode_config import (
    geonode_api_key,
    geonode_extract_url,
    geonode_poll_interval_sec,
    geonode_poll_timeout_sec,
    geonode_processing_mode,
    geonode_proxy_country,
    geonode_proxy_type,
    geonode_render_js,
    mobile_user_agent,
)


class GeonodeError(Exception):
    def __init__(self, message: str, code: str | None = None, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def _api_request(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    api_key = geonode_api_key()
    if not api_key:
        raise GeonodeError("GEONODE_API_KEY is not configured.")

    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise GeonodeError(f"Geonode HTTP {e.code}: {detail[:300]}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise GeonodeError(f"Geonode request failed: {e}") from e

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as e:
        raise GeonodeError("Geonode returned non-JSON response.") from e
    if not isinstance(parsed, dict):
        raise GeonodeError("Geonode returned unexpected response shape.")
    return parsed


def _extract_error(payload: dict[str, Any]) -> GeonodeError | None:
    err = payload.get("error")
    if not err:
        return None
    if isinstance(err, dict):
        message = str(err.get("message") or "Geonode extraction failed.")
        code = err.get("code")
        retryable = bool(err.get("retryable"))
        return GeonodeError(message, code=str(code) if code else None, retryable=retryable)
    return GeonodeError(str(err))


def _poll_job(job_id: str) -> dict[str, Any]:
    base = geonode_extract_url().rstrip("/")
    poll_url = f"{base}/{job_id}"
    deadline = time.time() + geonode_poll_timeout_sec()
    interval = geonode_poll_interval_sec()

    while time.time() < deadline:
        payload = _api_request("GET", poll_url, timeout=30.0)
        status = str(payload.get("status") or "").lower()
        if status in ("completed", "failed"):
            return payload
        time.sleep(interval)

    raise GeonodeError("Geonode extraction timed out waiting for job completion.", code="TIMEOUT")


def extract_html(
    page_url: str,
    *,
    render_js: bool | None = None,
    extra_headers: dict[str, str] | None = None,
    wait_until: str | None = None,
) -> str:
    """Fetch page HTML through Geonode residential proxies (Scraper API)."""
    use_render_js = render_js if render_js is not None else geonode_render_js()
    mode = geonode_processing_mode()

    headers = {"User-Agent": mobile_user_agent()}
    if extra_headers:
        headers.update(extra_headers)

    proxy: dict[str, str] = {"type": geonode_proxy_type()}
    country = geonode_proxy_country()
    if country:
        proxy["country"] = country

    body: dict[str, Any] = {
        "url": page_url,
        "formats": ["html"],
        "render_js": use_render_js,
        "processing_mode": mode,
        "proxy": proxy,
        "headers": headers,
    }
    if wait_until:
        body["wait_config"] = {"wait_until": wait_until, "wait_timeout": 30000}

    print(
        f"[geonode] extract {page_url} render_js={use_render_js} mode={mode}",
        flush=True,
    )
    response = _api_request("POST", geonode_extract_url(), body, timeout=90.0)

    if mode == "async":
        job_id = response.get("job_id")
        if not job_id:
            err = _extract_error(response)
            if err:
                raise err
            raise GeonodeError("Geonode async job did not return job_id.")
        response = _poll_job(str(job_id))

    err = _extract_error(response)
    if err:
        raise err

    data = response.get("data") or {}
    html = data.get("html")
    if not html or not str(html).strip():
        raise GeonodeError("Geonode returned empty HTML.", code="EMPTY_HTML")

    metadata = response.get("metadata") or {}
    print(
        f"[geonode] extracted html bytes={len(str(html))} "
        f"http_status={metadata.get('http_status')} duration_ms={metadata.get('duration_ms')}",
        flush=True,
    )
    return str(html)
