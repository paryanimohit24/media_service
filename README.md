# Media URL Import Service

Downloads audio from **public social URLs** using **Geonode Scraper API** (residential proxies) + `yt-dlp` + `ffmpeg`.

## Supported platforms

| Platform | Example URL |
|----------|-------------|
| Instagram | `https://www.instagram.com/reel/...` |
| YouTube | `https://www.youtube.com/watch?v=...`, `youtu.be/...`, `/shorts/...` |
| TikTok | `https://www.tiktok.com/@user/video/...`, `vm.tiktok.com/...` |
| Snapchat | `https://www.snapchat.com/t/...`, `story.snapchat.com/...` |

## Import strategy (2026-08)

1. **Flutter app (user IP)** — optional client-first for Instagram reels.
2. **Server** — Geonode Scraper API fetches page HTML via residential proxy, parses media URL, downloads CDN media, FFmpeg → m4a.
3. **yt-dlp fallback** — through Geonode HTTP proxy (`GEONODE_PROXY_URL`) or manual `YT_DLP_PROXY` when scrape parse fails.

When `GEONODE_API_KEY` is set, the server **does not** use datacenter IP directly (`GEONODE_ALLOW_DIRECT=false` by default). Free public proxy pool is disabled.

## Env (Cloud Run)

```env
GEONODE_API_KEY=your-scraper-api-key
GEONODE_ENABLED=true
GEONODE_ALLOW_DIRECT=false
GEONODE_PROCESSING_MODE=async
GEONODE_PROXY_COUNTRY=US
```

For YouTube/TikTok yt-dlp fallback, add proxy dashboard credentials:

```env
GEONODE_PROXY_URL=http://username:password@proxy.geonode.io:9000
```

## Local run

```bash
cd media_service
cp .env.example .env   # set GEONODE_API_KEY
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8001
```

```bash
python test_import.py "https://www.instagram.com/reel/XXXX/" --out test.m4a
python test_import.py "https://www.youtube.com/watch?v=XXXX" --out test.m4a
```

## Spring backend

```
url-import.enabled=true
url-import.service.url=http://localhost:8001
```

## Honest limits

- Geonode Scraper API charges per extraction request.
- Instagram HTML changes may require parser updates.
- YouTube/TikTok often need `GEONODE_PROXY_URL` for yt-dlp fallback (separate proxy credentials from Scraper API key).
- Instagram ToS / Play Store policy risk — feature behind `kEnableReelUrlImport`.
