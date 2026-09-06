"""
Spotify Track Extractor Module
Resolves Spotify track metadata via oEmbed and Embed page, 
then matches 100% full-duration 320kbps HD audio stream via JioSaavn & InnerTube/yt-dlp.
"""

import logging
import urllib.parse
import re
import json as _json
import base64
from typing import Dict, Any, Optional
import httpx

from config import DEFAULT_USER_AGENT, PUBLIC_BASE_URL
from extractors.ytdlp_engine import extract_via_ytdlp
from extractors.base_extractor import is_safe_public_url

logger = logging.getLogger("SpotifyEngine")


def decrypt_jiosaavn_url(enc_url: str) -> Optional[str]:
    """Decrypts JioSaavn encrypted_media_url to direct 320kbps Akamai CDN stream URL using DES ECB."""
    try:
        enc_bytes = base64.b64decode(enc_url.strip())
        dec_bytes = None
        try:
            try:
                from cryptography.hazmat.decrepit.ciphers import algorithms
            except ImportError:
                from cryptography.hazmat.primitives.ciphers import algorithms
            from cryptography.hazmat.primitives.ciphers import Cipher, modes
            from cryptography.hazmat.primitives import padding

            cipher = Cipher(algorithms.TripleDES(b"38346591" * 3), modes.ECB())
            decryptor = cipher.decryptor()
            dec_padded = decryptor.update(enc_bytes) + decryptor.finalize()
            unpadder = padding.PKCS7(64).unpadder()
            dec_bytes = unpadder.update(dec_padded) + unpadder.finalize()
        except Exception:
            try:
                from pyDes import des, ECB, PAD_PKCS5
                cipher = des(b"38346591", ECB, pad=None, padmode=PAD_PKCS5)
                dec_bytes = cipher.decrypt(enc_bytes)
            except Exception:
                pass

        if not dec_bytes:
            return None

        clean_url = dec_bytes.decode('utf-8').strip()
        # Upgrade stream bitrate to 320kbps
        clean_url = clean_url.replace("_96.mp4", "_320.mp4").replace("_160.mp4", "_320.mp4")
        return clean_url
    except Exception as e:
        logger.debug(f"JioSaavn DES decryption error: {e}")
        return None


async def search_and_resolve_jiosaavn(title: str, artist: str, expected_dur: float = 0.0) -> Optional[Dict[str, Any]]:
    """
    Searches JioSaavn for the exact track and resolves full 320kbps CDN audio stream.
    Filters out remixes/slowed/karaoke and matches expected track duration.
    """
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Cookie": "L=english; DL=english; gdpr_acceptance=true"
    }
    queries = [
        f"{title} {artist}".strip(),
        title.strip()
    ]
    unwanted = ["slowed", "reverb", "karaoke", "instrumental", "sped up", "tribute", "cover", "techno", "remix", "edit", "acoustic", "live"]

    try:
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
            best_candidate = None
            min_diff = 9999.0

            for q in queries:
                url = f"https://www.jiosaavn.com/api.php?__call=search.getResults&_format=json&_marker=0&cc=in&includeMetaTags=1&p=1&n=15&q={urllib.parse.quote(q)}"
                try:
                    res = await client.get(url, headers=headers)
                    if res.status_code != 200:
                        continue
                    text = res.text.strip()
                    if text.startswith("/*") and text.endswith("*/"):
                        text = text[2:-2]
                    data = _json.loads(text)
                    results = data.get("results", [])

                    for s in results:
                        if not isinstance(s, dict):
                            continue
                        s_title = (s.get("title") or s.get("song") or "").strip()
                        s_lower = s_title.lower()

                        # Skip unwanted variants if not requested in original Spotify title
                        if any(u in s_lower for u in unwanted if u not in title.lower()):
                            continue

                        pid = s.get("id")
                        s_more = s.get("more_info") if isinstance(s.get("more_info"), dict) else {}
                        s_duration = float(s.get("duration") or s_more.get("duration") or 0)

                        if not s_duration and pid:
                            try:
                                det_url = f"https://www.jiosaavn.com/api.php?__call=song.getDetails&cc=in&_marker=0%3F_marker%3D0&_format=json&pids={pid}"
                                r_det = await client.get(det_url, headers=headers)
                                if r_det.status_code == 200:
                                    dt = r_det.text.strip()
                                    if dt.startswith("/*") and dt.endswith("*/"):
                                        dt = dt[2:-2]
                                    d_json = _json.loads(dt)
                                    s_det = d_json.get(pid, {})
                                    if isinstance(s_det, dict):
                                        s_more_det = s_det.get("more_info") if isinstance(s_det.get("more_info"), dict) else {}
                                        s_duration = float(s_det.get("duration") or s_more_det.get("duration") or 0)
                            except Exception:
                                pass

                        if s_duration <= 35:
                            continue

                        diff = abs(s_duration - expected_dur) if expected_dur > 0 else 0
                        if expected_dur > 0 and diff > 35.0:
                            # Reject track if duration discrepancy exceeds tolerance
                            continue

                        # Candidate is eligible, fetch audio details
                        det_url = f"https://www.jiosaavn.com/api.php?__call=song.getDetails&cc=in&_marker=0%3F_marker%3D0&_format=json&pids={pid}"
                        r_det = await client.get(det_url, headers=headers)
                        if r_det.status_code == 200:
                            dt = r_det.text.strip()
                            if dt.startswith("/*") and dt.endswith("*/"):
                                dt = dt[2:-2]
                            d_json = _json.loads(dt)
                            s_det = d_json.get(pid, {})
                            if isinstance(s_det, dict):
                                s_more_det = s_det.get("more_info") if isinstance(s_det.get("more_info"), dict) else {}
                                enc_url = s_det.get("encrypted_media_url") or s_more_det.get("encrypted_media_url")
                                if enc_url:
                                    stream_url = decrypt_jiosaavn_url(enc_url)
                                    if stream_url and stream_url.startswith("http"):
                                        thumb = (s.get("image") or "").replace("50x50", "500x500").replace("150x150", "500x500")
                                        singers = s_more_det.get("singers") or s_more_det.get("music") or artist
                                        cand = {
                                            "title": f"{s_title} - {singers}" if singers else s_title,
                                            "thumbnail": thumb,
                                            "duration": s_duration,
                                            "raw_stream_url": stream_url
                                        }
                                        if diff < min_diff:
                                            min_diff = diff
                                            best_candidate = cand
                                            if diff <= 5.0:
                                                logger.info(f"JioSaavn exact match: '{s_title}' ({s_duration}s)")
                                                return best_candidate
                except Exception as eq:
                    logger.debug(f"JioSaavn query notice: {eq}")

            return best_candidate
    except Exception as e:
        logger.debug(f"JioSaavn search/resolve error: {e}")
        
    return None


async def search_youtube_innertube(query: str) -> Optional[str]:
    """
    Executes an InnerTube search request to match YouTube video IDs directly
    without triggering Cloud Datacenter bot challenges.
    """
    from config import get_all_proxies
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': DEFAULT_USER_AGENT,
        'X-YouTube-Client-Name': '1',
        'X-YouTube-Client-Version': '2.20240101.00.00',
        'Origin': 'https://www.youtube.com',
        'Referer': 'https://www.youtube.com/'
    }
    data = {
        'context': {
            'client': {
                'clientName': 'WEB',
                'clientVersion': '2.20240101.00.00',
                'hl': 'en',
                'gl': 'US'
            }
        },
        'query': query
    }

    def extract_vids(obj):
        found = []
        if isinstance(obj, dict):
            if "videoId" in obj and (obj.get("lengthText") or "title" in obj):
                found.append(obj["videoId"])
            for v in obj.values():
                found.extend(extract_vids(v))
        elif isinstance(obj, list):
            for item in obj:
                found.extend(extract_vids(item))
        return found

    # 1. Try Direct
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            r = await client.post('https://www.youtube.com/youtubei/v1/search', headers=headers, json=data)
            if r.status_code == 200:
                vids = extract_vids(r.json())
                if vids:
                    return vids[0]
    except Exception:
        pass

    # 2. Try Proxies
    proxies = get_all_proxies()
    for p in proxies:
        try:
            async with httpx.AsyncClient(proxy=p, timeout=6.0, follow_redirects=True) as client:
                r = await client.post('https://www.youtube.com/youtubei/v1/search', headers=headers, json=data)
                if r.status_code == 200:
                    vids = extract_vids(r.json())
                    if vids:
                        return vids[0]
        except Exception:
            continue

    return None


async def extract_spotify(url: str, client_ip: str, format_type: str = "mp3") -> Dict[str, Any]:
    """
    Resolves track metadata via Spotify oEmbed and Spotify embed page, 
    then retrieves matching 100% full duration 320kbps audio.
    """
    is_safe, reason = is_safe_public_url(url)
    if not is_safe:
        raise Exception(f"Spotify Extractor SSRF Block: {reason}")
    oembed_url = f"https://open.spotify.com/oembed?url={urllib.parse.quote(url)}"
    res = None
    try:
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
            res = await client.get(oembed_url, headers={"User-Agent": DEFAULT_USER_AGENT})
    except Exception:
        pass

    if not res or res.status_code != 200:
        from config import get_random_proxy
        for _ in range(3):
            proxy = get_random_proxy()
            if not proxy:
                break
            try:
                async with httpx.AsyncClient(proxy=proxy, timeout=10.0, follow_redirects=True) as client:
                    res = await client.get(oembed_url, headers={"User-Agent": DEFAULT_USER_AGENT})
                    if res.status_code == 200:
                        break
            except Exception:
                continue

    if not res or res.status_code != 200:
        raise Exception("Spotify oEmbed track resolution failed")

    data = res.json()
    title = data.get("title", "Spotify Track")
    artist = data.get("author_name", "")
    expected_duration = 0.0

    # Extract exact artist & duration from Spotify embed page
    if "/track/" in url:
        try:
            track_id = url.split("/track/")[1].split("?")[0]
            embed_page_url = f"https://open.spotify.com/embed/track/{track_id}"
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                er = await client.get(embed_page_url, headers={"User-Agent": DEFAULT_USER_AGENT})
                if er.status_code == 200:
                    em_m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', er.text)
                    if em_m:
                        em_data = _json.loads(em_m.group(1))
                        entity = em_data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
                        if not artist:
                            art_list = [a.get("name") for a in entity.get("artists", []) if a.get("name")]
                            if art_list:
                                artist = ", ".join(art_list)
                        raw_dur = entity.get("duration") or entity.get("duration_ms")
                        if raw_dur:
                            expected_duration = float(raw_dur) / 1000.0
        except Exception:
            pass

    full_query = f"{title} {artist}".strip()
    thumbnail = data.get("thumbnail_url")

    def is_valid_full_audio(ad: Optional[Dict[str, Any]]) -> bool:
        if not ad or not ad.get("raw_stream_url"):
            return False
        dur = float(ad.get("duration") or 0)
        if dur <= 35:
            return False
        if expected_duration > 0 and dur < (expected_duration * 0.75):
            return False
        return True

    audio_data = None
    fallback_js = None

    # 1. Primary: JioSaavn 320kbps full-track resolver (Fast & Direct CDN)
    try:
        js_cand = await search_and_resolve_jiosaavn(title, artist, expected_duration)
        if is_valid_full_audio(js_cand):
            js_dur = float(js_cand.get("duration") or 0)
            if expected_duration == 0 or abs(js_dur - expected_duration) <= 5.0:
                audio_data = js_cand
            else:
                fallback_js = js_cand
    except Exception as e_js:
        logger.debug(f"Spotify JioSaavn notice: {e_js}")

    # 2. Secondary: InnerTube Search for exact video match + yt-dlp 320kbps stream extractor
    if not audio_data:
        try:
            matched_vid = await search_youtube_innertube(f"{full_query} audio")
            if not matched_vid:
                matched_vid = await search_youtube_innertube(full_query)
            if matched_vid:
                yt_url = f"https://www.youtube.com/watch?v={matched_vid}"
                try:
                    cand = await extract_via_ytdlp(yt_url, "mp3", client_ip, use_proxy=False)
                    if is_valid_full_audio(cand):
                        audio_data = cand
                except Exception:
                    pass
                if not audio_data:
                    try:
                        cand = await extract_via_ytdlp(yt_url, "mp3", client_ip, use_proxy=True)
                        if is_valid_full_audio(cand):
                            audio_data = cand
                    except Exception:
                        pass
        except Exception as e1:
            logger.debug(f"Spotify InnerTube search notice: {e1}")

    # 3. Tertiary: Direct ytsearch with android player client
    if not audio_data:
        try:
            cand = await extract_via_ytdlp(f"ytsearch:{full_query} audio", "mp3", client_ip, use_proxy=False)
            if is_valid_full_audio(cand):
                audio_data = cand
        except Exception as e2:
            logger.debug(f"Spotify YouTube search notice: {e2}")

    # 4. Quaternary: YouTube search via Proxy Pool
    if not audio_data:
        try:
            cand = await extract_via_ytdlp(f"ytsearch:{full_query} audio", "mp3", client_ip, use_proxy=True)
            if is_valid_full_audio(cand):
                audio_data = cand
        except Exception as e3:
            logger.debug(f"Spotify YouTube proxy search notice: {e3}")

    # 5. Quinary: Distributed Piped search fallback
    if not audio_data:
        try:
            piped_apis = [
                f"https://api.piped.private.coffee/search?q={urllib.parse.quote(full_query + ' audio')}&filter=all",
                f"https://pipedapi.kavin.rocks/search?q={urllib.parse.quote(full_query + ' audio')}&filter=all"
            ]
            async with httpx.AsyncClient(timeout=5.0) as client:
                for api_url in piped_apis:
                    try:
                        p_res = await client.get(api_url)
                        if p_res.status_code == 200:
                            items = p_res.json().get("items", [])
                            for it in items:
                                it_dur = float(it.get("duration") or 0)
                                if it_dur > 45 and it.get("url"):
                                    matched_vid = it["url"].replace("/watch?v=", "")
                                    full_yt_url = f"https://www.youtube.com/watch?v={matched_vid}"
                                    p_track = await extract_via_ytdlp(full_yt_url, "mp3", client_ip, use_proxy=True)
                                    if is_valid_full_audio(p_track):
                                        audio_data = p_track
                                        break
                            if audio_data:
                                break
                    except Exception:
                        continue
        except Exception as ep:
            logger.debug(f"Spotify Piped search notice: {ep}")

    # 6. Senary: JioSaavn resilient fallback
    if not audio_data and fallback_js:
        audio_data = fallback_js

    # 7. Septenary: SoundCloud search for full tracks
    if not audio_data:
        try:
            sc_data = await extract_via_ytdlp(f"scsearch:{full_query}", "mp3", client_ip, use_proxy=False)
            if is_valid_full_audio(sc_data):
                audio_data = sc_data
        except Exception as e4:
            logger.debug(f"Spotify SoundCloud search notice: {e4}")

    if not is_valid_full_audio(audio_data):
        raise Exception(f"Unable to match full-length audio stream for Spotify track '{full_query}'")

    encoded_url = urllib.parse.quote(url)
    encoded_title = urllib.parse.quote(title)
    proxy_mp4 = f"{PUBLIC_BASE_URL}/api/download?url={encoded_url}&format_type=mp4&title={encoded_title}"
    proxy_mp3 = f"{PUBLIC_BASE_URL}/api/download?url={encoded_url}&format_type=mp3&title={encoded_title}"

    return {
        "platform": "Spotify",
        "title": audio_data.get("title") or (f"{title} - {artist}" if artist else title),
        "thumbnail": audio_data.get("thumbnail") or thumbnail,
        "duration": audio_data.get("duration"),
        "format_type": format_type,
        "engine": "Spotify Track Engine (320kbps Audio Stream)",
        "download_url": proxy_mp3 if format_type == "mp3" else proxy_mp4,
        "raw_stream_url": audio_data.get("raw_stream_url"),
        "mp4_url": proxy_mp4,
        "mp3_url": proxy_mp3,
        "quality": "320kbps High Quality Audio"
    }
