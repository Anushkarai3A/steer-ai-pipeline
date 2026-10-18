from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models import ContentAsset, User

router = APIRouter(prefix="/api/assets", tags=["assets"])


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


@router.get("/{asset_id}")
def download_asset(
    asset_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    asset = db.get(ContentAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found.")
    path = Path(asset.file_path)
    # path traversal protection: assets must live under the generated directory
    if not _is_within(path, settings.generated_path) or not path.exists():
        raise HTTPException(status_code=404, detail="Asset file is missing from storage.")
    return FileResponse(
        path,
        media_type=asset.mime,
        filename=asset.filename,
        content_disposition_type="attachment",
    )


@router.get("/{asset_id}/inline")
def inline_asset(
    asset_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    asset = db.get(ContentAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found.")
    path = Path(asset.file_path)
    if not _is_within(path, settings.generated_path) or not path.exists():
        raise HTTPException(status_code=404, detail="Asset file is missing from storage.")
    return FileResponse(path, media_type=asset.mime)
