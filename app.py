"""
Universal media extraction service for Mixify.
- GET  /api/extract/video|audio  — resolve CDN stream URLs (no merge)
- GET  /api/download             — server ffmpeg transcode fallback (HLS / blocked CDN)
- POST /import-audio             — backward-compatible Spring proxy contract
"""
from __future__ import annotations

import asyncio
import glob
import logging
import os
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from functools import partial
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from config import CORS_ORIGINS, PORT, TEMP_DIR, TEMP_FILE_MAX_AGE_SECONDS, RATE_LIMIT_PER_MINUTE
from extractors.base_extractor import get_client_ip
from api.system_router import router as system_router
from api.extract_router import router as extract_router
from api.download_router import router as download_router
from import_audio import (
    AUDIO_SIZE_HEADER,
    BYTES_DOWNLOADED_HEADER,
    DOWNLOAD_MODE_HEADER,
    import_audio_from_url,
    is_supported_url,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("MediaService")

_YOUTUBE_BOT_BLOCK_MESSAGE = (
    "YouTube blocked server download from datacenter IP. "
    "Try importing on your phone network first."
)

_ip_request_timestamps: dict[str, list[float]] = defaultdict(list)


@asynccontextmanager
async def lifespan(_: FastAPI):
    asyncio.create_task(_periodic_temp_cleanup())
    logger.info("Media service started on port %s", PORT)
    yield


app = FastAPI(
    title="Mixify Media Service",
    description="Social URL extraction, download fallback, and audio import.",
    version="4.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def rate_limiting_middleware(request: Request, call_next):
    path = request.url.path
    if path in ("/health", "/docs", "/openapi.json", "/favicon.ico"):
        return await call_next(request)

    client_ip = get_client_ip(request)
    now = time.time()
    _ip_request_timestamps[client_ip] = [t for t in _ip_request_timestamps[client_ip] if now - t < 60]
    if len(_ip_request_timestamps[client_ip]) >= RATE_LIMIT_PER_MINUTE:
        return StreamingResponse(
            iter([b'{"detail": "Rate limit exceeded. Please wait a minute before retrying."}']),
            status_code=429,
            media_type="application/json",
        )

    _ip_request_timestamps[client_ip].append(now)
    return await call_next(request)


async def _periodic_temp_cleanup():
    while True:
        try:
            await asyncio.sleep(900)
            now = time.time()
            pattern = os.path.join(TEMP_DIR, "tmp*")
            for fpath in glob.glob(pattern):
                try:
                    if os.path.isfile(fpath) and (now - os.path.getmtime(fpath)) > TEMP_FILE_MAX_AGE_SECONDS:
                        os.remove(fpath)
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("Periodic temp cleanup notice: %s", exc)


class ImportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    url: str = Field(..., min_length=8, max_length=2048)
    client_attempted: Optional[bool] = Field(default=None, alias="clientAttempted")


def _run_import(url: str, client_ip: str) -> tuple[bytes, str, str, int, int, str]:
    started = time.time()
    result = import_audio_from_url(url, client_ip=client_ip)
    elapsed_ms = int((time.time() - started) * 1000)
    logger.info(
        "import-audio ok duration_ms=%s bytes_downloaded=%s audio_size=%s download_mode=%s response_bytes=%s",
        elapsed_ms,
        result.bytes_downloaded,
        result.audio_size_bytes,
        result.download_mode,
        len(result.data),
    )
    return (
        result.data,
        result.filename,
        result.media_type,
        result.bytes_downloaded,
        result.audio_size_bytes,
        result.download_mode,
    )


@app.post("/import-audio", response_class=Response)
async def import_audio(body: ImportRequest, request: Request):
    url = body.url.strip()
    if not is_supported_url(url):
        raise HTTPException(
            status_code=400,
            detail="Unsupported URL. Paste a public Instagram, YouTube, TikTok, Snapchat, or Facebook link.",
        )
    client_ip = get_client_ip(request)
    try:
        loop = asyncio.get_running_loop()
        data, filename, media_type, bytes_downloaded, audio_size, download_mode = await loop.run_in_executor(
            None,
            partial(_run_import, url, client_ip),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("import-audio failed for %s", url)
        detail = str(exc).strip() or "Import failed."
        if "not a bot" in detail.lower() or "sign in to confirm" in detail.lower():
            detail = _YOUTUBE_BOT_BLOCK_MESSAGE
        raise HTTPException(status_code=502, detail=detail) from exc

    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            BYTES_DOWNLOADED_HEADER: str(bytes_downloaded),
            AUDIO_SIZE_HEADER: str(audio_size),
            DOWNLOAD_MODE_HEADER: download_mode,
        },
    )


app.include_router(system_router)
app.include_router(extract_router)
app.include_router(download_router)
