# Mixify Media Service

Unified social URL engine (demo extractor stack) for **audio import** and **video studio** resolution.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Health check |
| `GET` | `/api/extract/video` | Resolve video CDN stream URL (JSON) |
| `GET` | `/api/extract/audio` | Resolve audio CDN stream URL (JSON) |
| `GET` | `/api/download` | Server ffmpeg transcode fallback (HLS / blocked CDN) — **no merge** |
| `POST` | `/import-audio` | Backward-compatible Spring proxy contract (audio bytes) |

There is **no** `/api/merge` on this service. Video merge runs on-device in the Flutter app.

## Secrets (private repo — demo defaults in git)

- **Proxies:** Webshare list is in `services/proxy_service.py` (same as demo). Override with `PROXIES` env if needed.
- **Cookies:** `cookies/*.txt` committed in repo (same as demo). Refresh files when sessions expire.

## Deploy

Use `deploy-media-import-service.sh` (Cloud Run `media-import-service`, port `8001`). Set:

- `PUBLIC_BASE_URL` — public service URL (used in extract `download_url` fields)

`PROXIES` and `COOKIES_DIR` are optional — defaults work out of the box like the demo.
