"""
Manual test: POST /import-audio pipeline.

Usage:
  python test_import.py "https://www.instagram.com/reel/XXXX/"
  python test_import.py "https://www.youtube.com/watch?v=XXXX"
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from import_audio import import_audio_from_url, is_supported_url


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
    parser = argparse.ArgumentParser(description="Test /import-audio engine")
    parser.add_argument("url", nargs="?", help="Instagram / YouTube / TikTok / Snapchat / Facebook URL")
    parser.add_argument("--env-file", default=".env", help="Optional .env file (default: .env)")
    parser.add_argument("--out", default="import_test_output.mp3", help="Output audio file path")
    args = parser.parse_args()

    if Path(args.env_file).is_file():
        _load_env_file(args.env_file)
        print(f"Loaded env from {args.env_file}")

    url = (args.url or os.environ.get("TEST_REEL_URL") or "").strip()
    if not url:
        print("Error: pass URL as argument or set TEST_REEL_URL in .env", file=sys.stderr)
        return 1

    if not is_supported_url(url):
        print("Error: unsupported URL for /import-audio", file=sys.stderr)
        return 1

    print(f"Importing: {url}")
    try:
        result = import_audio_from_url(url)
        if not result.data:
            print("Error: downloaded file is empty", file=sys.stderr)
            return 2
        out_path = Path(args.out)
        out_path.write_bytes(result.data)
        print(f"OK: saved {len(result.data)} bytes -> {out_path.resolve()}")
        print(f"Filename: {result.filename}")
        print(f"bytes_downloaded={result.bytes_downloaded} audio_size={result.audio_size_bytes} mode={result.download_mode}")
        return 0
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
