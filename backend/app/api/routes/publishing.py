from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.core.errors import APIError, bad_request, not_found
from app.models import ContentDeliverable, PublishingItem, User
from app.schemas.review import PublishConfirmIn, PublishingItemOut
from app.services.review.workflow import confirm_published, publishing_eligibility, sync_publishing_item

router = APIRouter(prefix="/api/publishing", tags=["publishing"])


class PublishingRow(PublishingItemOut):
    format: str = ""
    project_id: str = ""
    project_name: str = ""
    version_number: int = 0
    concept: str = ""
    deliverable_status: str = ""
    eligible: bool = False
    reasons: list[str] = []
    has_export: bool = False


@router.get("", response_model=list[PublishingRow])
def queue(
    status: str | None = None,
    format: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PublishingRow]:
    query = db.query(PublishingItem)
    items = query.all()
    rows: list[PublishingRow] = []
    for item in items:
        d = item.deliverable
        if d is None:
            continue
        if status and item.status != status:
            continue
        if format and d.format != format:
            continue
        eligible, reasons = publishing_eligibility(d)
        version = d.current_version
        rows.append(PublishingRow(
            **PublishingItemOut.model_validate(item).model_dump(),
            format=d.format,
            project_id=d.project_id,
            project_name=d.project.name if d.project else "",
            version_number=version.version_number if version else 0,
            concept=d.concept,
            deliverable_status=d.status,
            eligible=eligible,
            reasons=reasons,
            has_export=any(
                a.kind == "export_bundle"
                for a in (version.assets if version else [])
            ),
        ))
    order = {"ready_to_publish": 0, "queued": 1, "published": 2, "withdrawn": 3}
    rows.sort(key=lambda r: (order.get(r.status, 9), r.created_at or ""))
    return rows


@router.post("/{item_id}/prepare", response_model=PublishingRow)
def prepare(
    item_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PublishingRow:
    item = db.get(PublishingItem, item_id)
    if item is None:
        raise not_found("Publishing item")
    d = db.get(ContentDeliverable, item.deliverable_id)
    if d is None:
        raise not_found("Deliverable")
    sync_publishing_item(db, d)
    db.commit()
    db.refresh(item)
    eligible, reasons = publishing_eligibility(d)
    if not eligible and item.status != "ready_to_publish":
        raise APIError(409, "Cannot prepare for publishing: " + " | ".join(reasons), "not_eligible")
    version = d.current_version
    return PublishingRow(
        **PublishingItemOut.model_validate(item).model_dump(),
        format=d.format,
        project_id=d.project_id,
        project_name=d.project.name if d.project else "",
        version_number=version.version_number if version else 0,
        concept=d.concept,
        deliverable_status=d.status,
        eligible=eligible,
        reasons=reasons,
        has_export=any(a.kind == "export_bundle" for a in (version.assets if version else [])),
    )


@router.post("/{item_id}/confirm", response_model=PublishingRow)
def confirm(
    item_id: str,
    body: PublishConfirmIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("doctor", "admin", "editor")),
) -> PublishingRow:
    """Manual publishing confirmation: the reviewer asserts they published it externally.

    Steer does not publish to Instagram by itself; this records the confirmation.
    """
    item = db.get(PublishingItem, item_id)
    if item is None:
        raise not_found("Publishing item")
    d = db.get(ContentDeliverable, item.deliverable_id)
    if d is None:
        raise not_found("Deliverable")
    item = confirm_published(db, d, note=f"confirmed by {user.name}", external_url=body.external_url)
    db.commit()
    eligible, reasons = publishing_eligibility(d)
    version = d.current_version
    return PublishingRow(
        **PublishingItemOut.model_validate(item).model_dump(),
        format=d.format,
        project_id=d.project_id,
        project_name=d.project.name if d.project else "",
        version_number=version.version_number if version else 0,
        concept=d.concept,
        deliverable_status=d.status,
        eligible=eligible,
        reasons=reasons,
        has_export=any(a.kind == "export_bundle" for a in (version.assets if version else [])),
    )
