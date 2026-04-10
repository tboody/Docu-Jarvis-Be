from pathlib import Path

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    binary_ok = Path(settings.docu_jarvis_binary).exists()
    return {
        "status": "ok",
        "binary_found": binary_ok,
        "binary_path": settings.docu_jarvis_binary,
    }
