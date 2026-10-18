from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.serialize import project_out
from app.core.config import settings
from app.core.database import get_db
from app.models import (
    ContentDeliverable,
    ContentVersion,
    EvidenceClaim,
    PipelineRun,
    ProjectStatus,
    ResearchProject,
    ResearchSource,
    Review,
    ReviewComment,
    SourceStatus,
    User,
)
from app.schemas.project import ClaimStatsOut, DashboardStats, PendingReviewOut

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
def stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> DashboardStats:
    projects = db.query(ResearchProject).all()
    sources = db.query(ResearchSource).all()
    deliverables = db.query(ContentDeliverable).all()
    versions = db.query(ContentVersion).all()
    runs = db.query(PipelineRun).order_by(PipelineRun.created_at.desc()).all()
    reviews = db.query(Review).order_by(Review.created_at.desc()).limit(20).all()
    comments = db.query(ReviewComment).order_by(ReviewComment.created_at.desc()).limit(20).all()

    papers_processed = sum(1 for s in sources if s.status == SourceStatus.extracted.value)
    drafts_generated = sum(1 for d in deliverables if d.current_version_id)
    awaiting = [d for d in deliverables if d.status == "awaiting_review"]
    approved = [d for d in deliverables if d.status in {"approved", "ready_to_publish", "published"}]
    failed_runs = [r for r in runs if r.status == "failed"]

    recent_projects = sorted(
        projects, key=lambda p: p.updated_at or p.created_at or datetime(1970, 1, 1), reverse=True
    )[:5]

    activity: list[dict] = []
    for r in reviews:
        activity.append({
            "type": "review",
            "text": f"{r.reviewer_name or 'Reviewer'} {r.decision} {r.deliverable.format if r.deliverable else 'content'} "
                    f"(v{r.version_number})",
            "at": _iso(r.created_at),
            "project_id": r.deliverable.project_id if r.deliverable else None,
        })
    for run in runs:
        activity.append({
            "type": "pipeline",
            "text": f"Pipeline {run.kind} run {run.status} for project “{_project_name(projects, run.project_id)}”",
            "at": _iso(run.finished_at or run.created_at),
            "project_id": run.project_id,
        })
    for c in comments:
        activity.append({
            "type": "comment",
            "text": f"{c.reviewer_name or 'Commenter'} commented on {c.deliverable.format if c.deliverable else 'content'}: "
                    f"{(c.body or '')[:80]}",
            "at": _iso(c.created_at),
            "project_id": c.deliverable.project_id if c.deliverable else None,
        })
    activity.sort(key=lambda a: a["at"] or "", reverse=True)

    pipeline_status = []
    for p in projects:
        latest = sorted(p.pipeline_runs, key=lambda r: r.created_at or r.id, reverse=True)
        latest = latest[0] if latest else None
        stages = sorted(latest.stages, key=lambda s: s.ordinal) if latest else []
        done = sum(1 for s in stages if s.status == "succeeded")
        failed_stage = next((s for s in stages if s.status == "failed"), None)
        pipeline_status.append({
            "project_id": p.id,
            "project_name": p.name,
            "project_status": p.status,
            "run_status": latest.status if latest else None,
            "run_kind": latest.kind if latest else None,
            "run_id": latest.id if latest else None,
            "stages_total": len(stages),
            "stages_succeeded": done,
            "failed_stage": failed_stage.label if failed_stage else None,
            "failed_error": failed_stage.error if failed_stage else None,
        })

    failed_stage_runs = []
    for run in failed_runs[:10]:
        for s in run.stages:
            if s.status == "failed":
                failed_stage_runs.append({
                    "run_id": run.id,
                    "project_id": run.project_id,
                    "project_name": _project_name(projects, run.project_id),
                    "stage": s.label,
                    "error": s.error,
                    "at": _iso(run.finished_at or run.created_at),
                })

    # Pending reviews (awaiting doctor action), newest first.
    pending_reviews: list[PendingReviewOut] = []
    for d in sorted(awaiting, key=lambda x: x.updated_at or datetime(1970, 1, 1), reverse=True):
        v = d.current_version
        latest_approval_review = next(
            (r for r in sorted(d.reviews, key=lambda r: r.id, reverse=True)
             if r.decision == "approved"),
            None,
        )
        submitted_at = None
        for r in sorted(d.reviews, key=lambda r: r.id, reverse=True):
            submitted_at = r.created_at
            break
        pending_reviews.append(PendingReviewOut(
            deliverable_id=d.id,
            project_id=d.project_id,
            project_name=_project_name(projects, d.project_id),
            format=d.format,
            version_id=v.id if v else None,
            version_number=v.version_number if v else None,
            status=d.status,
            submitted_at=submitted_at,
        ))

    # Claim stats (persisted rows only).
    claims = db.query(EvidenceClaim).all()
    claim_stats = ClaimStatsOut(total=len(claims))
    for c in claims:
        s = getattr(c, "status", None)
        if s in {"supported", "partially_supported", "needs_human_review", "conflicting", "unsupported"}:
            setattr(claim_stats, s, getattr(claim_stats, s) + 1)
        if getattr(c, "risk_level", None) == "high":
            claim_stats.high_risk += 1

    return DashboardStats(
        projects=len(projects),
        papers_processed=papers_processed,
        drafts_generated=drafts_generated,
        awaiting_review=len(awaiting),
        approved_deliverables=len(approved),
        failed_jobs=len(failed_runs),
        ai_enabled=settings.ai_enabled,
        recent_projects=[project_out(p) for p in recent_projects],
        recent_activity=activity[:14],
        pipeline_status=pipeline_status,
        failed_stage_runs=failed_stage_runs,
        pending_reviews=pending_reviews,
        claim_stats=claim_stats,
    )


def _project_name(projects: list[ResearchProject], project_id: str) -> str:
    return next((p.name for p in projects if p.id == project_id), project_id)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()
