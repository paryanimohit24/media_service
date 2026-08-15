"""
Manual test: download audio via Geonode Scraper API (+ yt-dlp fallback).

Usage:
  python test_import.py "https://www.instagram.com/reel/XXXX/"
  python test_import.py "https://www.youtube.com/watch?v=XXXX"
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from importer import import_audio_from_url, is_supported_url
from proxy_config import proxy_status, warm_pool


def _load_env_file(path: str) -> None:
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Env file not found: {path}")
    for line in file_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    parser = argparse.ArgumentParser(description="Test social URL import via Geonode")
    parser.add_argument("url", nargs="?", help="Instagram / YouTube / TikTok / Snapchat URL")
    parser.add_argument("--env-file", default=".env", help="Optional .env file (default: .env)")
    parser.add_argument(
        "--proxy",
        help="Optional admin override YT_DLP_PROXY for this run only",
    )
    parser.add_argument(
        "--out",
        default="proxy_test_output.m4a",
        help="Output audio file path (default: proxy_test_output.m4a)",
    )
    args = parser.parse_args()

    if Path(args.env_file).is_file():
        _load_env_file(args.env_file)
        print(f"Loaded env from {args.env_file}")

    if args.proxy:
        os.environ["YT_DLP_PROXY"] = args.proxy

    warm_pool()
    status = proxy_status()
    print("Proxy status:", status)

    url = (args.url or os.environ.get("TEST_REEL_URL") or "").strip()
    if not url:
        print(
            "Error: pass URL as argument or set TEST_REEL_URL in .env",
            file=sys.stderr,
        )
        return 1

    if not is_supported_url(url):
        print("Error: unsupported URL for this service", file=sys.stderr)
        return 1

    print(f"Importing: {url}")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = import_audio_from_url(url, tmpdir)
            data = Path(result.audio_path).read_bytes()
            if not data:
                print("Error: downloaded file is empty", file=sys.stderr)
                return 2
            out_path = Path(args.out)
            out_path.write_bytes(data)
            print(f"OK: saved {len(data)} bytes -> {out_path.resolve()}")
            print(f"Title: {result.title}")
            return 0
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
