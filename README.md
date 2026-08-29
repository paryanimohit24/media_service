# Media URL Import Service

Downloads audio from **public social URLs** using **yt-dlp** + **ffmpeg**.

## Supported platforms

| Platform | Example URL |
|----------|-------------|
| Instagram | `https://www.instagram.com/reel/...` |
| YouTube | `https://www.youtube.com/watch?v=...`, `youtu.be/...`, `/shorts/...` |
| TikTok | `https://www.tiktok.com/@user/video/...`, `vm.tiktok.com/...` |
| Snapchat | `https://www.snapchat.com/t/...`, `story.snapchat.com/...` |

## Import strategy

1. **Flutter app (user IP)** — Instagram reels download on the phone network first.
2. **Server fallback** — yt-dlp direct from Cloud Run IP (optional `YT_DLP_PROXY` if blocked).

## Env (Cloud Run)

```env
YT_DLP_AUTO_PROXY=false
YT_DLP_PROXY_FALLBACK_ATTEMPTS=0
# Optional:
# YT_DLP_PROXY=http://user:pass@host:port
# YT_DLP_COOKIES_FILE=/path/to/cookies.txt
```

## Local run

```bash
cd media_service
cp .env.example .env
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8001
```

```bash
python test_import.py "https://www.instagram.com/reel/XXXX/" --out test.m4a
```

## Spring backend

```
url-import.enabled=true
url-import.service.url=http://localhost:8001
```

## Honest limits

- Instagram reels should use the **phone client path** (user IP) — server datacenter IP may fail.
- YouTube/TikTok may block datacenter IPs without optional `YT_DLP_PROXY`.
- Instagram ToS / Play Store policy risk — feature behind `kEnableReelUrlImport`.
