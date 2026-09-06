"""
System & Health API Router
Provides system health check and user public IP detection endpoints.
"""

from fastapi import APIRouter, Request
from extractors.base_extractor import get_client_ip

router = APIRouter(tags=["System"])


@router.get("/api/client-ip")
async def get_client_ip_endpoint(request: Request):
    """Returns the detected public client IP address."""
    return {"ip": get_client_ip(request)}


@router.get("/health")
async def health_check_endpoint():
    """Health check endpoint for container orchestrators and monitoring tools."""
    from services.proxy_service import get_all_proxies
    return {
        "status": "ok",
        "service": "mixify-media-service",
        "proxies_configured": len(get_all_proxies()),
    }


@router.get("/api")
@router.get("/api/status")
async def root_endpoint():
    """Root metadata endpoint."""
    return {
        "status": "online",
        "service": "Mixify Media Service",
        "version": "4.0.0",
        "endpoints": {
            "extract_video": "/api/extract/video?url={url}",
            "extract_audio": "/api/extract/audio?url={url}",
            "download": "/api/download?url={url}&format_type={mp4|mp3}",
            "import_audio": "POST /import-audio",
            "client_ip": "/api/client-ip",
            "health": "/health",
            "docs": "/docs",
        },
    }
