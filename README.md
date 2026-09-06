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

## Secrets

- **Proxies:** set `PROXIES` env (comma-separated). Never commit credentials.
- **Cookies:** mount Netscape cookie files via `COOKIES_DIR` or `COOKIES_FILE` (Secret Manager / volume). Files under `cookies/*.txt` are gitignored.

## Local test

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8001
python3 test_import.py "https://www.instagram.com/reel/XXXX/"
```

## Deploy

Use `deploy-media-import-service.sh` (Cloud Run `media-import-service`, port `8001`). Set:

- `PUBLIC_BASE_URL` — public service URL (used in extract `download_url` fields)
- `PROXIES` — optional residential proxies
- `COOKIES_DIR` — optional mounted cookie directory
