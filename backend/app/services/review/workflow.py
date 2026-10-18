from __future__ import annotations

"""Doctor review + approval gate (Stage 8) and publishing eligibility (Stage 9).

Rules enforced here (server-side, never client-only):
  * A deliverable can only be approved by a doctor/admin for the EXACT current
    version (version id + number + content hash are recorded).
  * A material edit to an approved version invalidates that approval and
    returns the deliverable to review.
  * Only an approved current version with no blocking validation errors can
    reach ready_to_publish.
  * Content is never "published" without an explicit manual confirmation.
"""

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.errors import APIError, bad_request, conflict, forbidden, not_found
from app.core.ids import new_id
from app.models import (
    ContentDeliverable,
    ContentVersion,
    PublishingItem,
    Review,
    ReviewComment,
    User,
)
from app.services.validation.validate import claim_publication_blockers, has_blocking_errors

DOCTOR_ROLES = {"doctor", "admin"}


def material_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def require_reviewer(user: User) -> None:
    if user.role not in DOCTOR_ROLES:
        raise forbidden(
            "Only a doctor or admin reviewer can approve, reject or request changes on content."
        )


def snapshot_claim_ids(payload: dict) -> list[str]:
    ids: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            if "claim_ids" in node and isinstance(node["claim_ids"], list):
                ids.extend(str(c) for c in node["claim_ids"])
            if node.get("claim_id"):
                ids.append(str(node["claim_id"]))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(payload)
    return sorted(set(ids))


def apply_edit(
    db: Session,
    deliverable: ContentDeliverable,
    version: ContentVersion,
    new_payload: dict,
    *,
    note: str = "",
    editor: User | None = None,
) -> tuple[ContentVersion, bool, str | None]:
    """Apply a material edit. Returns (version, approval_invalidated, message)."""
    new_hash = material_hash(new_payload)

    if new_hash == version.material_hash:
        return version, False, "No content change detected."

    approval_attached = deliverable.approved_version_id == version.id
    had_approval = bool(deliverable.approved_version_id)

    if approval_attached:
        # RULE 4: material edit after approval invalidates the approval and
        # returns the deliverable to review. The approved artifact is preserved
        # as a separate version.
        approved_version = version
        new_version = ContentVersion(
            id=new_id("cv"),
            deliverable_id=deliverable.id,
            version_number=(max((v.version_number for v in deliverable.versions), default=0) + 1),
            payload=new_payload,
            generation_mode=version.generation_mode,
            generation_mode_label=version.generation_mode_label,
            model_name=version.model_name,
            prompt_version=version.prompt_version,
            material_hash=new_hash,
            validation={},
            validation_status="pending",
        )
        db.add(new_version)
        db.flush()
        db.expire(deliverable, ["versions"])
        deliverable.current_version_id = new_version.id
        deliverable.approved_version_id = None
        deliverable.status = "awaiting_review"
        _add_system_comment(
            db,
            deliverable,
            new_version,
            f"Material edit applied to previously approved v{approved_version.version_number}. "
            "Approval invalidated — the deliverable returned to doctor review.",
            editor,
        )
        return new_version, True, "Approval invalidated: the content changed materially after approval."

    # no approval attached to this version
    version.payload = new_payload
    version.material_hash = new_hash
    version.validation_status = "pending"

    invalidated = False
    message = None
    if deliverable.approved_version_id and deliverable.approved_version_id != version.id:
        deliverable.approved_version_id = None
        invalidated = True
        message = "Stale approval cleared."
    if deliverable.status in {"approved", "ready_to_publish"}:
        deliverable.approved_version_id = None
        deliverable.status = "awaiting_review"
        invalidated = True
        message = message or "Approval invalidated: the approved content was modified."
        _add_system_comment(
            db, deliverable, version,
            "Material edit applied to approved content. Approval invalidated and the deliverable "
            "was returned to doctor review.", editor,
        )
    return version, invalidated, message


def submit_for_review(db: Session, deliverable: ContentDeliverable) -> None:
    if deliverable.status in {"awaiting_review"}:
        raise conflict("This deliverable is already awaiting doctor review.")
    if deliverable.status in {"published"}:
        raise conflict("Published deliverables cannot be re-submitted without withdrawing.")
    if deliverable.status in {"approved", "ready_to_publish"}:
        raise conflict("Approved content is already past review. Edit it first to trigger re-review.")
    if not deliverable.current_version_id:
        raise bad_request("Generate content before sending it for review.")
    deliverable.status = "awaiting_review"


def revalidate_project(db: Session, project) -> list[dict]:
    """Re-run validation for every deliverable that has a current version.

    Claim status/evidence changes (PATCH, source removal, startup repair) can
    flip a stored validation result — always re-run and re-sync the publishing
    item together, so eligibility never trusts a stale result.
    """
    from app.services.validation.validate import validate_payload

    # expire_on_commit=False: force fresh collections before re-validating
    db.expire(project, ["claims", "deliverables"])
    claims_by_id = {c.id: c for c in project.claims}
    results: list[dict] = []
    for d in project.deliverables:
        v = d.current_version
        if v is None:
            continue
        validation = validate_payload(d.format, v.payload, project, claims_by_id)
        v.validation = validation
        v.validation_status = validation["status"]
        if validation["status"] == "failed" and d.status in {"draft", "processing"}:
            d.status = "needs_evidence_review"
        elif validation["status"] != "failed" and d.status == "needs_evidence_review":
            d.status = "draft"
        db.commit()
        sync_publishing_item(db, d)
        db.commit()
        results.append({"format": d.format, "status": validation["status"], "counts": validation["counts"]})
    return results


def decide(
    db: Session,
    deliverable: ContentDeliverable,
    user: User,
    *,
    decision: str,
    comments: str = "",
    version_id: str | None = None,
) -> Review:
    require_reviewer(user)
    version = deliverable.current_version
    if version is None:
        raise bad_request("There is no content version to review.")
    if deliverable.status != "awaiting_review":
        raise conflict("This deliverable is not awaiting review.")
    if version_id and version_id != version.id:
        raise conflict("You are reviewing an outdated version. Reload and review the current content.")

    review = Review(
        id=new_id("rev"),
        deliverable_id=deliverable.id,
        version_id=version.id,
        version_number=version.version_number,
        reviewer_id=user.id,
        reviewer_name=user.name,
        decision=decision,
        comments=comments,
        payload_snapshot={
            "material_hash": version.material_hash,
            "claim_ids": snapshot_claim_ids(version.payload),
            "mode": version.generation_mode,
        },
    )
    db.add(review)

    if decision == "approved":
        deliverable.approved_version_id = version.id
        deliverable.status = "approved"
    elif decision == "rejected":
        deliverable.approved_version_id = None
        deliverable.status = "rejected"
    elif decision == "changes_requested":
        deliverable.approved_version_id = None
        deliverable.status = "changes_requested"
    else:
        raise bad_request(f"Unknown decision: {decision}")
    db.flush()
    return review


def publishing_eligibility(deliverable: ContentDeliverable) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    version = deliverable.current_version
    if version is None:
        reasons.append("No content version exists.")
        return False, reasons
    if not deliverable.approved_version_id:
        reasons.append("No doctor approval recorded.")
    elif deliverable.approved_version_id != version.id:
        reasons.append("Approval applies to an older version than the current content.")
    elif version.material_hash == "" :
        reasons.append("Content hash missing.")
    if deliverable.status not in {"approved", "ready_to_publish"}:
        reasons.append(f"Status is '{deliverable.status}', not approved.")
    # Direct claim-level gate: never trust a possibly-stale stored validation
    # run to decide that linked claims are publishable.
    claims_by_id = {c.id: c for c in deliverable.project.claims}
    for cid in snapshot_claim_ids(version.payload):
        claim = claims_by_id.get(cid)
        if claim is None:
            reasons.append(f"Claim {cid} does not exist in the evidence registry.")
            continue
        reasons.extend(claim_publication_blockers(claim))
    validation = version.validation or {}
    if validation.get("status") == "pending" or not validation:
        reasons.append("Validation has not been run for the current version.")
    elif has_blocking_errors(validation):
        errs = [i["message"] for i in validation.get("issues", []) if i.get("severity") == "error"]
        reasons.append("Blocking validation errors: " + "; ".join(errs[:4]))
    return (len(reasons) == 0), reasons


def sync_publishing_item(db: Session, deliverable: ContentDeliverable) -> PublishingItem | None:
    """Create/update the publishing item to reflect current eligibility."""
    if deliverable.approved_version_id is None:
        if deliverable.publishing_item:
            item = deliverable.publishing_item
            if item.status != "published":
                db.delete(item)
                db.flush()
        return None

    eligible, reasons = publishing_eligibility(deliverable)
    version = deliverable.current_version
    if version is None:
        return None

    item = deliverable.publishing_item
    if item is None:
        item = PublishingItem(
            id=new_id("pub"),
            deliverable_id=deliverable.id,
            version_id=version.id,
            status="queued",
            method="manual_download",
        )
        db.add(item)
    item.version_id = version.id
    item.method = "manual_download"

    if item.status == "published":
        item.note = item.note  # published state is sticky until withdrawn
    elif eligible:
        item.status = "ready_to_publish"
        deliverable.status = "ready_to_publish"
        item.note = "Approved current version with passing validation. Download assets and publish manually."
    else:
        item.status = "queued"
        item.note = "Not ready: " + " | ".join(reasons)
    db.flush()
    return item


def confirm_published(db: Session, deliverable: ContentDeliverable, *, note: str = "", external_url: str | None = None) -> PublishingItem:
    item = deliverable.publishing_item
    if item is None or item.status != "ready_to_publish":
        raise APIError(
            409,
            "Only items in 'ready to publish' state can be confirmed as published.",
            "not_eligible",
        )
    item.status = "published"
    item.published_at = datetime.now(timezone.utc)
    suffix = note.strip()
    if external_url:
        suffix = (suffix + " | " if suffix else "") + f"URL: {external_url}"
    item.note = ("Manually confirmed as published by a reviewer. " + suffix).strip()
    deliverable.status = "published"
    db.flush()
    return item


def add_comment(db: Session, deliverable: ContentDeliverable, user: User, body: str, anchor: str | None = None) -> ReviewComment:
    comment = ReviewComment(
        id=new_id("cmt"),
        deliverable_id=deliverable.id,
        version_id=deliverable.current_version_id,
        reviewer_id=user.id,
        reviewer_name=user.name,
        body=body,
        anchor=anchor,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


def _add_system_comment(db: Session, deliverable: ContentDeliverable, version: ContentVersion, body: str, user: User | None) -> None:
    db.add(
        ReviewComment(
            id=new_id("cmt"),
            deliverable_id=deliverable.id,
            version_id=version.id,
            reviewer_id=user.id if user else None,
            reviewer_name=(user.name if user else "system"),
            body=body,
            anchor="system",
        )
    )
