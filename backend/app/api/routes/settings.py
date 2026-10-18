from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.config import settings
from app.models import User

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings")
def read_settings(user: User = Depends(get_current_user)) -> dict:
    """Non-secret runtime configuration for the Settings page.

    Never exposes credentials, API keys or secrets.
    """
    db_engine = "postgresql" if settings.database_url.startswith("postgres") else "sqlite"
    try:
        from app.services.rendering.pptx_builder import pptx_available

        pptx_ok = pptx_available()
    except Exception:
        pptx_ok = False
    try:
        import imageio_ffmpeg  # noqa: F401

        ffmpeg_ok = True
    except Exception:
        ffmpeg_ok = False

    return {
        "app": settings.app_name,
        "version": settings.pipeline_version,
        "environment": settings.environment,
        "demo": True,
        "ai": {
            "enabled": settings.ai_enabled,
            "provider": settings.llm_provider if settings.ai_enabled else "none",
            "model": settings.llm_model if settings.ai_enabled else None,
        },
        "database": {
            "engine": db_engine,
            "connected": True,
        },
        "worker": {
            "kind": "in-process-threadpool",
            "max_workers": 2,
        },
        "rendering": {
            "ffmpeg_available": ffmpeg_ok,
            "pptx_available": pptx_ok,
            "reel_fps": settings.reel_fps,
            "carousel_max_slides": settings.carousel_max_slides,
        },
        "limits": {
            "max_upload_bytes": settings.max_upload_bytes,
            "min_sources_per_project": settings.min_sources_per_project,
            "max_sources_per_project": settings.max_sources_per_project,
        },
    }
