"""YouTube Innertube player API — fetch direct audio URL without yt-dlp."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from http_headers import mobile_user_agent

_INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
_PLAYER_URL = f"https://www.youtube.com/youtubei/v1/player?key={_INNERTUBE_KEY}"

_YOUTUBE_ID = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/|live/)|youtu\.be/)([\w-]{6,})",
    re.IGNORECASE,
)


def youtube_video_id(url: str) -> str | None:
    match = _YOUTUBE_ID.search(url.strip())
    return match.group(1) if match else None


def _urlopen(req: urllib.request.Request, proxy: str | None, timeout: int = 30):
    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
        return opener.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


def _fetch_embed_context(video_id: str, proxy: str | None) -> dict[str, str]:
    """Visitor data from the embed page helps Innertube on datacenter IPs."""
    url = f"https://www.youtube.com/embed/{video_id}?hl=en&persist_hl=1"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": mobile_user_agent(),
            "Accept-Language": "en-US,en;q=0.9",
        },
        method="GET",
    )
    try:
        with _urlopen(req, proxy, timeout=25) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[youtube-innertube] embed context failed: {e}", flush=True)
        return {}

    context: dict[str, str] = {}
    visitor_match = re.search(r'"VISITOR_DATA":"([^"]+)"', html)
    if visitor_match:
        context["visitorData"] = visitor_match.group(1)
    client_match = re.search(r'"INNERTUBE_CONTEXT_CLIENT_VERSION":"([^"]+)"', html)
    if client_match:
        context["clientVersion"] = client_match.group(1)
    return context


def _pick_audio_url(streaming_data: dict) -> str | None:
    formats: list[dict] = []
    for key in ("adaptiveFormats", "formats"):
        raw = streaming_data.get(key)
        if isinstance(raw, list):
            formats.extend([f for f in raw if isinstance(f, dict)])

    audio_direct = []
    for fmt in formats:
        mime = str(fmt.get("mimeType") or "").lower()
        url = fmt.get("url")
        if url and "audio" in mime and str(url).startswith("http"):
            bitrate = int(fmt.get("bitrate") or fmt.get("averageBitrate") or 0)
            audio_direct.append((bitrate, str(url)))

    if not audio_direct:
        return None
    audio_direct.sort(key=lambda x: x[0], reverse=True)
    return audio_direct[0][1]


def _innertube_request(
    video_id: str,
    client_name: str,
    client_version: str,
    user_agent: str,
    proxy: str | None,
    embed_context: dict[str, str],
) -> dict | None:
    client: dict = {
        "clientName": client_name,
        "clientVersion": client_version,
        "hl": "en",
        "gl": "US",
        "userAgent": user_agent,
    }
    if client_name == "ANDROID":
        client["androidSdkVersion"] = 34
    if embed_context.get("visitorData"):
        client["visitorData"] = embed_context["visitorData"]

    payload = json.dumps({"context": {"client": client}, "videoId": video_id}).encode("utf-8")
    req = urllib.request.Request(
        _PLAYER_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": user_agent,
            "Origin": "https://www.youtube.com",
            "Referer": f"https://www.youtube.com/embed/{video_id}",
        },
        method="POST",
    )
    try:
        with _urlopen(req, proxy, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"[youtube-innertube] {client_name} HTTP {e.code}", flush=True)
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[youtube-innertube] {client_name} failed: {e}", flush=True)
        return None

    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def fetch_youtube_audio_url(video_id: str, proxy: str | None = None) -> str | None:
    """Return a direct googlevideo audio URL if Innertube responds with one."""
    embed_context = _fetch_embed_context(video_id, proxy)
    embed_version = embed_context.get("clientVersion") or "2.20250122.01.00"
    ua_mobile = mobile_user_agent()
    clients = [
        ("TV_EMBEDDED", embed_version, ua_mobile),
        ("WEB_EMBEDDED", embed_version, ua_mobile),
        ("MWEB", "2.20250122.01.00", ua_mobile),
        (
            "IOS",
            "19.49.4",
            "com.google.ios.youtube/19.49.4 (iPhone14C3; U; CPU iOS 17_0 like Mac OS X)",
        ),
        (
            "ANDROID",
            "19.49.4",
            "com.google.android.youtube/19.49.4 (Linux; U; Android 14) gzip",
        ),
        ("ANDROID_SDKLESS", "19.49.4", ua_mobile),
    ]
    proxy_label = proxy or "direct"
    print(f"[youtube-innertube] trying clients via {proxy_label}", flush=True)
    for name, version, ua in clients:
        data = _innertube_request(video_id, name, version, ua, proxy, embed_context)
        if not data:
            continue
        status = data.get("playabilityStatus") or {}
        if str(status.get("status") or "").upper() != "OK":
            reason = status.get("reason") or status.get("status")
            print(f"[youtube-innertube] {name} playability={reason}", flush=True)
            continue
        streaming = data.get("streamingData")
        if not isinstance(streaming, dict):
            continue
        audio_url = _pick_audio_url(streaming)
        if audio_url:
            print(f"[youtube-innertube] audio URL via {name} ({proxy_label})", flush=True)
            return audio_url
    return None
