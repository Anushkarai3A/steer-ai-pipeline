from __future__ import annotations

from app.models import (
    ContentDeliverable,
    EvidenceClaim,
    PipelineRun,
    ResearchProject,
    ResearchSource,
)
from app.schemas.content import DeliverableDetailOut, DeliverableOut, VersionOut
from app.schemas.evidence import ClaimOut, EvidenceOut
from app.schemas.project import ProjectDetailOut, ProjectOut, SourceDetailOut, SourceOut
from app.schemas.review import PipelineRunOut, ReviewOut, CommentOut, PublishingItemOut


def source_out(source: ResearchSource) -> SourceOut:
    return SourceOut.model_validate(source)


def source_detail_out(source: ResearchSource) -> SourceDetailOut:
    base = SourceOut.model_validate(source)
    doc = source.document
    pages = doc.pages if doc else []
    preview = ""
    if doc and doc.full_text:
        preview = doc.full_text[:4000]
        if len(doc.full_text) > 4000:
            preview += "\n… [truncated in preview; full text stored]"
    return SourceDetailOut(
        **base.model_dump(),
        pages=[{"page": p["page"], "chars": len(p["text"]), "preview": p["text"][:1500]} for p in pages],
        full_text_preview=preview,
        metadata=(doc.metadata_json if doc else {}) or {},
        extraction_method=(doc.method if doc else None),
    )


def project_out(project: ResearchProject) -> ProjectOut:
    base = ProjectOut.model_validate(project)
    base.source_count = len(project.sources)
    base.claim_count = len(project.claims)
    base.deliverable_count = len(project.deliverables)
    return base


def project_detail_out(project: ResearchProject) -> ProjectDetailOut:
    base = project_out(project)
    findings = [
        {
            "id": f.id,
            "source_id": f.source_id,
            "category": f.category,
            "text": f.text,
            "page": f.page,
            "section": f.section,
        }
        for f in sorted(project.findings, key=lambda x: (x.category, x.id))
    ]
    return ProjectDetailOut(
        **base.model_dump(),
        sources=[source_out(s) for s in project.sources],
        summary=project.summary,
        findings=findings,
    )


def evidence_out(ev) -> EvidenceOut:
    out = EvidenceOut.model_validate(ev)
    if ev.source:
        out.source_title = ev.source.title
        out.source_filename = ev.source.original_filename
        out.source_year = ev.source.year
        out.source_journal = ev.source.journal
    return out


def claim_out(claim: EvidenceClaim) -> ClaimOut:
    base = ClaimOut.model_validate(claim)
    base.evidence = [evidence_out(e) for e in claim.evidence]
    return base


def version_out(version) -> VersionOut:
    from app.schemas.content import AssetOut

    out = VersionOut.model_validate(version)
    out.assets = sorted(
        [AssetOut.model_validate(a) for a in version.assets],
        key=lambda a: (a.kind, a.filename),
    )
    return out


def deliverable_out(d: ContentDeliverable) -> DeliverableOut:
    return DeliverableOut.model_validate(d)


def deliverable_detail_out(d: ContentDeliverable, blocked_claims: list[str] | None = None) -> DeliverableDetailOut:
    from datetime import datetime

    base = deliverable_out(d)
    versions = sorted(d.versions, key=lambda v: v.version_number)
    current = d.current_version
    epoch = datetime(1970, 1, 1)
    return DeliverableDetailOut(
        **base.model_dump(),
        versions=[version_out(v) for v in versions],
        current_version=version_out(current) if current else None,
        comments=[CommentOut.model_validate(c).model_dump(mode="json") for c in d.comments],
        reviews=[
            ReviewOut.model_validate(r).model_dump(mode="json")
            for r in sorted(d.reviews, key=lambda r: r.created_at or epoch, reverse=True)
        ],
        publishing_item=PublishingItemOut.model_validate(d.publishing_item).model_dump(mode="json") if d.publishing_item else None,
        blocked_claims=blocked_claims or [],
    )


def pipeline_run_out(run: PipelineRun) -> PipelineRunOut:
    return PipelineRunOut.model_validate(run)
