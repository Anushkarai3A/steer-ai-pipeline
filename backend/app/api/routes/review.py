from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.api.serialize import deliverable_detail_out
from app.core.database import get_db
from app.core.errors import bad_request, not_found
from app.models import ContentDeliverable, User
from app.schemas.content import DeliverableDetailOut
from app.schemas.review import CommentIn, CommentOut, ReviewIn, ReviewOut
from app.services.review.workflow import add_comment, decide, sync_publishing_item

router = APIRouter(prefix="/api", tags=["review"])


def _get_deliverable(db: Session, deliverable_id: str) -> ContentDeliverable:
    d = db.get(ContentDeliverable, deliverable_id)
    if d is None:
        raise not_found("Deliverable")
    return d


def _blocked_claims(d: ContentDeliverable) -> list[str]:
    v = d.current_version
    if not v or not v.validation:
        return []
    return sorted({
        i["claim_id"] for i in v.validation.get("issues", [])
        if i.get("severity") == "error" and i.get("claim_id")
    })


@router.get("/review/queue", response_model=list[DeliverableDetailOut])
def review_queue(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DeliverableDetailOut]:
    """All deliverables awaiting a doctor decision (decisions themselves stay role-gated)."""
    ds = db.query(ContentDeliverable).filter(ContentDeliverable.status == "awaiting_review").all()
    ds.sort(key=lambda d: str(d.updated_at or d.created_at or ""))
    return [deliverable_detail_out(d, _blocked_claims(d)) for d in ds]


@router.get("/deliverables/{deliverable_id}/reviews", response_model=list[ReviewOut])
def list_reviews(
    deliverable_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ReviewOut]:
    d = _get_deliverable(db, deliverable_id)
    return [ReviewOut.model_validate(r) for r in sorted(d.reviews, key=lambda r: r.id, reverse=True)]


@router.post("/deliverables/{deliverable_id}/reviews", response_model=DeliverableDetailOut, status_code=201)
def submit_review(
    deliverable_id: str,
    body: ReviewIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("doctor", "admin")),
) -> DeliverableDetailOut:
    """Approve / reject / request changes. Server-side role check; never client-only."""
    d = _get_deliverable(db, deliverable_id)
    review = decide(
        db, d, user,
        decision=body.decision,
        comments=body.comments,
        version_id=body.version_id,
    )
    db.commit()
    sync_publishing_item(db, d)
    db.commit()
    if review.decision == "approved" and body.comments:
        # keep reviewer comment attached to the version as well
        add_comment(db, d, user, f"Review decision — approved: {body.comments}", anchor="approval")
    d = _get_deliverable(db, deliverable_id)
    return deliverable_detail_out(d, _blocked_claims(d))


@router.get("/deliverables/{deliverable_id}/comments", response_model=list[CommentOut])
def list_comments(
    deliverable_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CommentOut]:
    d = _get_deliverable(db, deliverable_id)
    return [CommentOut.model_validate(c) for c in d.comments]


@router.post("/deliverables/{deliverable_id}/comments", response_model=CommentOut, status_code=201)
def create_comment(
    deliverable_id: str,
    body: CommentIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommentOut:
    d = _get_deliverable(db, deliverable_id)
    if not body.body.strip():
        raise bad_request("Comment body cannot be empty.")
    comment = add_comment(db, d, user, body.body.strip(), anchor=body.anchor)
    return CommentOut.model_validate(comment)
