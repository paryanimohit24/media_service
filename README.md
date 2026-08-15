# Media URL Import Service (experimental)

Downloads audio from **public Instagram reel/post URLs** using `yt-dlp` + `ffmpeg`.

## Import strategy (2026-08)

1. **Flutter app (user's real IP)** — fetches reel page, downloads CDN media, FFmpeg extracts audio locally (~5–25s).
2. **Server fallback** — Spring → this service when client import fails:
   - Direct (Cloud Run IP) once, fast fail (`socket_timeout` 20s)
   - Optional admin `YT_DLP_PROXY` once
   - Up to 3 free proxies (no pre-health-check; yt-dlp fails fast)

Proxy pool is **not** warmed on container startup (lazy refresh on first fallback only).

## Env (Cloud Run)

```env
YT_DLP_AUTO_PROXY=false
YT_DLP_PROXY_FALLBACK_ATTEMPTS=3
YT_DLP_PROXY_HEALTH_CHECK=false
YT_DLP_PROXY_HEALTH_TIMEOUT_SEC=1
```

Optional paid proxy:

```env
YT_DLP_PROXY=http://user:pass@host:port
```

## Local run

```bash
cd media_import_service
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8001
```

```powershell
python test_import.py "https://www.instagram.com/reel/XXXX/" --out test.m4a
```

## Spring backend

```
url-import.enabled=true
url-import.service.url=http://localhost:8001
```

## Honest limits

- Client-first works for many public reels; Instagram HTML changes may require parser updates.
- Free public proxies remain unreliable — client-first reduces how often they are needed.
- Instagram ToS / Play Store policy risk — feature behind `kEnableReelUrlImport`.
