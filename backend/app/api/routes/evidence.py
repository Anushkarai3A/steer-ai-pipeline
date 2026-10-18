from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_project_or_404, require_roles
from app.api.serialize import claim_out
from app.core.database import get_db
from app.core.errors import bad_request, not_found
from app.models import ClaimEvidence, EvidenceClaim, User
from app.schemas.evidence import CLAIM_STATUSES, ClaimOut, ClaimUpdate, SourceExcerptOut
from app.services.review.workflow import revalidate_project as revalidate_all_versions
from app.services.validation.validate import claim_safety_checks, validate_payload

router = APIRouter(prefix="/api", tags=["evidence"])


@router.get("/projects/{project_id}/claims", response_model=list[ClaimOut])
def list_claims(
    project_id: str,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ClaimOut]:
    project = get_project_or_404(db, project_id)
    claims = sorted(project.claims, key=lambda c: c.id)
    if status:
        if status not in CLAIM_STATUSES:
            raise bad_request(f"Unknown status '{status}'. Expected one of {CLAIM_STATUSES}.")
        claims = [c for c in claims if c.status == status]
    return [claim_out(c) for c in claims]


@router.get("/claims/{claim_id}", response_model=ClaimOut)
def get_claim(claim_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ClaimOut:
    claim = db.get(EvidenceClaim, claim_id)
    if claim is None:
        raise not_found("Claim")
    return claim_out(claim)


@router.patch("/claims/{claim_id}", response_model=ClaimOut)
def update_claim(
    claim_id: str,
    body: ClaimUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("doctor", "admin")),
) -> ClaimOut:
    """Evidence status changes are a reviewer action — server-side role enforced."""
    claim = db.get(EvidenceClaim, claim_id)
    if claim is None:
        raise not_found("Claim")
    if body.status is not None and body.status != claim.status:
        if body.status in {"supported", "partially_supported"}:
            # Fresh query — never trust a possibly-stale relationship here, and
            # require an actual supporting passage (a contradicts-only row or a
            # note that merely mentions a page does not count).
            supporting = (
                db.query(ClaimEvidence.id)
                .filter(
                    ClaimEvidence.claim_id == claim.id,
                    ClaimEvidence.relation == "supports",
                    ClaimEvidence.excerpt != "",
                )
                .first()
            )
            if supporting is None:
                raise bad_request(
                    "Cannot mark a claim as supported when no evidence passage is linked to it. "
                    "Re-run evidence linking or keep it marked for human review."
                )
        claim.status = body.status
    if body.verification_notes is not None:
        claim.verification_notes = body.verification_notes
    if body.claim_text is not None and body.claim_text.strip():
        claim.claim_text = body.claim_text.strip()
        claim.status = "needs_human_review"
        claim.verification_notes = (
            "Claim text was edited — status reset to 'needs human review' until evidence is re-checked. "
            + (claim.verification_notes or "")
        ).strip()
    if body.limitations is not None:
        claim.limitations = body.limitations
    db.commit()
    db.refresh(claim)

    # Claim status changes can unblock/block publishing eligibility.
    revalidate_all_versions(db, claim.project)
    db.refresh(claim)
    return claim_out(claim)


@router.get("/evidence/{evidence_id}/excerpt", response_model=SourceExcerptOut)
def evidence_excerpt(
    evidence_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SourceExcerptOut:
    ev = db.get(ClaimEvidence, evidence_id)
    if ev is None:
        raise not_found("Evidence record")
    source = ev.source
    surrounding = ""
    if source and source.document:
        page_text = next(
            (p["text"] for p in source.document.pages if p["page"] == ev.page), source.document.full_text[:3000]
        )
        idx = page_text.find(ev.excerpt[:80])
        if idx >= 0:
            start = max(0, idx - 600)
            surrounding = page_text[start: idx + len(ev.excerpt) + 600]
            prefix = "…" if start > 0 else ""
            suffix = "…" if idx + len(ev.excerpt) + 600 < len(page_text) else ""
            surrounding = prefix + surrounding + suffix
        else:
            surrounding = page_text[:1600]
    return SourceExcerptOut(
        source_id=ev.source_id,
        title=source.title if source else None,
        page=ev.page,
        section=ev.section,
        excerpt=ev.excerpt,
        surrounding_text=surrounding,
        doi=ev.doi or (source.doi if source else None),
        url=ev.url or (source.canonical_url if source else None),
    )


@router.post("/projects/{project_id}/revalidate")
def revalidate_project(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Re-run validation on all current versions (e.g. after resolving claims)."""
    project = get_project_or_404(db, project_id)
    return {"results": revalidate_all_versions(db, project)}


@router.get("/projects/{project_id}/safety-checks")
def project_safety_checks(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Aggregate deterministic per-claim safety checks for the Evidence Lab.

    Surfaces evidence-status, language and overreach risks on each claim so a
    doctor/editor sees them before content generation. Not a clinical fact-check.
    """
    project = get_project_or_404(db, project_id)
    claims = sorted(project.claims, key=lambda c: c.id)
    rows = []
    totals: dict[str, int] = {"error": 0, "warning": 0}
    for c in claims:
        checks = claim_safety_checks(c)
        for chk in checks:
            sev = chk.get("severity")
            if sev in totals:
                totals[sev] += 1
        rows.append({
            "claim_id": c.id,
            "claim_text": c.claim_text,
            "status": c.status,
            "risk_level": c.risk_level,
            "checks": checks,
        })

    claims_by_id = {c.id: c for c in claims}
    deliverables = []
    for d in project.deliverables:
        v = d.current_version
        if v is None:
            continue
        validation = validate_payload(d.format, v.payload, project, claims_by_id)
        deliverables.append({
            "deliverable_id": d.id,
            "format": d.format,
            "version_number": v.version_number,
            "status": validation["status"],
            "errors": validation["counts"]["errors"],
            "warnings": validation["counts"]["warnings"],
        })

    return {
        "project_id": project.id,
        "note": (
            "Deterministic rule-based safety checks; not a clinical fact-check. "
            "Doctor review is still required before publishing."
        ),
        "totals": totals,
        "claims": rows,
        "deliverables": deliverables,
    }
