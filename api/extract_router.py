"""
Extract API Router
Provides dedicated endpoints for video and audio stream extraction.
"""

from fastapi import APIRouter, Request, Query
from extractors.base_extractor import get_client_ip
from extractors.dispatcher import process_media_extraction

router = APIRouter(prefix="/api/extract", tags=["Extraction"])


@router.get("/video")
async def extract_video_endpoint(request: Request, url: str = Query(..., description="Target video URL")):
    """Dedicated Video Stream Extraction Endpoint (/api/extract/video)"""
    client_ip = get_client_ip(request)
    return await process_media_extraction(url, format_type="mp4", client_ip=client_ip)


@router.get("/audio")
async def extract_audio_endpoint(request: Request, url: str = Query(..., description="Target audio/video URL")):
    """Dedicated Audio Stream Extraction Endpoint (/api/extract/audio)"""
    client_ip = get_client_ip(request)
    return await process_media_extraction(url, format_type="mp3", client_ip=client_ip)


@router.get("")
async def extract_universal_endpoint(
    request: Request,
    url: str = Query(..., description="Target media URL"),
    format_type: str = Query("mp4", description="mp4 or mp3")
):
    """Universal Extraction Endpoint (/api/extract)"""
    client_ip = get_client_ip(request)
    return await process_media_extraction(url, format_type=format_type, client_ip=client_ip)
