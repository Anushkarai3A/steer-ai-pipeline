from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import bad_request, conflict, not_found
from app.core.ids import new_id
from app.models import ClaimEvidence, EvidenceClaim, ProjectStatus, ResearchProject, ResearchSource, SourceStatus


def _safe_filename(name: str) -> str:
    name = Path(name or "upload.pdf").name  # strip any path components
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return name[:120] or "upload.pdf"


async def save_upload(project_id: str, upload: UploadFile, db: Session) -> ResearchSource:
    project = db.get(ResearchProject, project_id)
    if project is None:
        raise not_found("Project")

    filename = _safe_filename(upload.filename or "upload.pdf")
    if not filename.lower().endswith(".pdf"):
        raise bad_request("Only PDF files are supported. Use DOI/URL add for other sources.")
    if len(project.sources) >= settings.max_sources_per_project:
        raise bad_request(f"A project accepts at most {settings.max_sources_per_project} sources.")

    data = await upload.read()
    if not data:
        raise bad_request("The uploaded file is empty.")
    if len(data) > settings.max_upload_bytes:
        raise bad_request(f"File exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB limit.")

    sha = hashlib.sha256(data).hexdigest()
    dup = (
        db.query(ResearchSource)
        .filter(ResearchSource.project_id == project_id, ResearchSource.sha256 == sha)
        .first()
    )
    if dup:
        raise conflict(f"Duplicate source: this file is already in the project as “{dup.title or dup.original_filename}”.")

    source_id = new_id("src")
    dest_dir = settings.upload_path / project_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{source_id}.pdf"
    dest.write_bytes(data)

    source = ResearchSource(
        id=source_id,
        project_id=project_id,
        kind="pdf",
        original_filename=filename,
        file_path=str(dest),
        sha256=sha,
        byte_size=len(data),
        status=SourceStatus.uploaded.value,
        title=Path(filename).stem.replace("_", " ").replace("-", " ") or None,
    )
    db.add(source)
    _touch_project_status(db, project)
    db.commit()
    db.refresh(source)
    return source


def add_source_by_reference(
    db: Session,
    project_id: str,
    *,
    kind: str,
    doi: str | None = None,
    url: str | None = None,
    title: str | None = None,
) -> ResearchSource:
    project = db.get(ResearchProject, project_id)
    if project is None:
        raise not_found("Project")
    if len(project.sources) >= settings.max_sources_per_project:
        raise bad_request(f"A project accepts at most {settings.max_sources_per_project} sources.")

    if kind == "doi":
        if not doi:
            raise bad_request("A DOI is required for DOI sources.")
        doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi.strip(), flags=re.I)
        if not re.match(r"^10\.\d{4,9}/\S+$", doi):
            raise bad_request("That does not look like a valid DOI (expected format 10.xxxx/xxxxx).")
        canonical = f"https://doi.org/{doi}"
    elif kind == "url":
        if not url:
            raise bad_request("A URL is required for URL sources.")
        if not re.match(r"^https?://", url.strip(), re.I):
            raise bad_request("URLs must start with http:// or https://")
        canonical = url.strip()
        doi = None
    else:
        raise bad_request(f"Unsupported source kind: {kind}")

    sha = hashlib.sha256(f"{kind}:{doi or canonical}".encode()).hexdigest()
    dup = (
        db.query(ResearchSource)
        .filter(ResearchSource.project_id == project_id, ResearchSource.sha256 == sha)
        .first()
    )
    if dup:
        raise conflict("This reference is already in the project.")

    source = ResearchSource(
        id=new_id("src"),
        project_id=project_id,
        kind=kind,
        doi=doi,
        url=canonical if kind == "url" else None,
        canonical_url=canonical,
        sha256=sha,
        status=SourceStatus.uploaded.value,
        title=title,
    )
    db.add(source)
    _touch_project_status(db, project)
    db.commit()
    db.refresh(source)
    return source


def remove_source(db: Session, source: ResearchSource) -> None:
    project = source.project
    if project and project.status == ProjectStatus.processing.value:
        raise conflict("Cannot remove a source while the project pipeline is running.")
    # Delete this source's evidence rows explicitly (instead of relying on the
    # database CASCADE) and remember which claims they supported. Otherwise the
    # claims keep a 'supported' status and a note pointing at a passage that no
    # longer exists — the Evidence Lab "supported with 0 passages" bug.
    affected_claim_ids = sorted({
        row[0]
        for row in db.query(ClaimEvidence.claim_id).filter(ClaimEvidence.source_id == source.id)
    })
    db.query(ClaimEvidence).filter(ClaimEvidence.source_id == source.id).delete(
        synchronize_session=False
    )
    if source.file_path:
        Path(source.file_path).unlink(missing_ok=True)
    db.delete(source)
    db.commit()

    from app.services.claims.evidence_link import reconcile_claim

    reconciled: list[str] = []
    for cid in affected_claim_ids:
        claim = db.get(EvidenceClaim, cid)
        if claim is not None and reconcile_claim(db, claim):
            reconciled.append(cid)
    if reconciled:
        db.commit()
        if project is not None:
            # Claims lost evidence: re-run validation so stored results,
            # deliverable status and publishing eligibility stay honest.
            db.expire_all()
            from app.services.review.workflow import revalidate_project

            revalidate_project(db, project)


def _touch_project_status(db: Session, project: ResearchProject) -> None:
    if project.status == ProjectStatus.ready.value:
        project.status = ProjectStatus.draft.value
        project.summary_status = "pending"
    project.summary = None if project.summary_status != "ready" else project.summary


def duplicate_upload_check(db: Session, project_id: str, sha: str) -> ResearchSource | None:
    return (
        db.query(ResearchSource)
        .filter(ResearchSource.project_id == project_id, ResearchSource.sha256 == sha)
        .first()
    )
