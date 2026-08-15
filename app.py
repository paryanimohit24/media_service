"""
FastAPI service: import audio from supported social URLs (Instagram reel/post).
POST /import-audio  { "url": "https://www.instagram.com/reel/..." }
"""
from __future__ import annotations

import asyncio
import re
import tempfile
import time
from contextlib import asynccontextmanager
from functools import partial
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, ConfigDict

from importer import import_audio_from_url, is_supported_url
from proxy_config import proxy_status


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Lazy proxy pool refresh — only when a request actually needs fallback proxies.
    yield


app = FastAPI(title="Media URL Import", lifespan=lifespan)


class ImportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    url: str = Field(..., min_length=8, max_length=2048)
    client_attempted: Optional[bool] = Field(default=None, alias="clientAttempted")


def _safe_filename(title: str, ext: str) -> str:
    base = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")
    if not base:
        base = "imported_audio"
    if len(base) > 80:
        base = base[:80]
    return f"{base}.{ext}"


def _run_import(url: str, client_attempted: bool | None = None) -> tuple[bytes, str, str]:
    started = time.time()
    with tempfile.TemporaryDirectory() as tmpdir:
        result = import_audio_from_url(url, tmpdir)
        with open(result.audio_path, "rb") as f:
            data = f.read()
        if not data:
            raise RuntimeError("Downloaded audio file is empty.")
        elapsed_ms = int((time.time() - started) * 1000)
        strategy = "server-fallback" if client_attempted else "server-direct"
        print(
            f"[media-import] strategy={strategy} client_attempted={bool(client_attempted)} "
            f"duration_ms={elapsed_ms} bytes={len(data)}",
            flush=True,
        )
        filename = _safe_filename(result.title, result.ext)
        media_type = "audio/mp4" if result.ext == "m4a" else "application/octet-stream"
        return data, filename, media_type


@app.post("/import-audio", response_class=Response)
async def import_audio(body: ImportRequest):
    url = body.url.strip()
    if not is_supported_url(url):
        raise HTTPException(
            status_code=400,
            detail="Unsupported URL. Paste a public Instagram reel or post link.",
        )
    try:
        loop = asyncio.get_running_loop()
        data, filename, media_type = await loop.run_in_executor(
            None,
            partial(_run_import, url, body.client_attempted),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        print(f"[media-import] failed for {url}: {e}", flush=True)
        raise HTTPException(
            status_code=502,
            detail="Could not download audio from this link. It may be private or unavailable.",
        ) from e

    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},

    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "media-url-import", **proxy_status()}
