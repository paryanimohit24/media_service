"""
Download API Router
Provides direct stream download with browser-compatible H.264/AAC normalization.
"""

import os
import tempfile
import logging
from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import StreamingResponse

from extractors.base_extractor import get_client_ip, clean_target_url, sanitize_filename
from extractors.dispatcher import process_media_extraction
from services.downloader_service import download_media_async, probe_and_normalize_for_playback

logger = logging.getLogger("DownloadRouter")
router = APIRouter(prefix="/api/download", tags=["Download"])


@router.get("")
async def download_stream_endpoint(
    request: Request,
    url: str = Query(..., description="Target media URL"),
    format_type: str = Query("mp4", description="mp4 or mp3"),
    title: str = Query("media", description="Custom filename for download")
):
    """Direct Proxy Stream Download Endpoint (/api/download)"""
    client_ip = get_client_ip(request)
    cleaned_url = clean_target_url(url)
    ext = "mp3" if format_type.lower() == "mp3" else "mp4"
    filename = sanitize_filename(title, ext)
    content_type = "audio/mpeg" if ext == "mp3" else "video/mp4"

    # Step 1: Extract direct media stream URL
    extraction_res = await process_media_extraction(cleaned_url, format_type, client_ip)
    raw_stream_url = extraction_res["data"].get("raw_stream_url", "")
    if not raw_stream_url:
        raise HTTPException(status_code=400, detail="Unable to resolve raw media stream URL")

    # Step 2: Download stream to temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix=f"_dl.{ext}") as tf1:
        tmp_raw = tf1.name
    with tempfile.NamedTemporaryFile(delete=False, suffix=f"_final.{ext}") as tf2:
        tmp_final = tf2.name

    try:
        downloaded_file = await download_media_async(
            target_url=cleaned_url,
            raw_stream_url=raw_stream_url,
            is_video=(ext == "mp4"),
            base_path=tmp_raw,
            client_ip=client_ip
        )

        if not downloaded_file or not os.path.exists(downloaded_file) or os.path.getsize(downloaded_file) < 1000:
            raise HTTPException(status_code=500, detail="Media stream download failed.")

        # Step 3: Ensure codec compatibility for browsers (H.264/AAC)
        playback_ready_file = probe_and_normalize_for_playback(downloaded_file, tmp_final, is_video=(ext == "mp4"))

        # Step 4: Stream file back to client and clean up
        def stream_generator():
            with open(playback_ready_file, "rb") as f:
                while chunk := f.read(65536):
                    yield chunk
            for fpath in [tmp_raw, tmp_final, downloaded_file]:
                if fpath and os.path.exists(fpath):
                    try:
                        os.remove(fpath)
                    except Exception:
                        pass

        return StreamingResponse(
            stream_generator(),
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Expose-Headers": "Content-Disposition",
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Download processing failed: {e}")
        for fpath in [tmp_raw, tmp_final]:
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except Exception:
                    pass
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
