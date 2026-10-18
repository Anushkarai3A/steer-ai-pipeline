from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_project_or_404, require_roles
from app.api.serialize import project_detail_out, project_out, source_detail_out, source_out
from app.core.database import get_db
from app.core.errors import bad_request, forbidden, not_found
from app.core.ids import new_id
from app.models import ProjectStatus, ResearchProject, User
from app.schemas.project import ProjectCreate, ProjectDetailOut, ProjectOut, SourceCreate, SourceDetailOut, SourceOut
from app.schemas.review import PipelineRunOut
from app.api.serialize import pipeline_run_out
from app.services.ingestion import ingest
from app.services.sample_project import create_sample_project
from app.workers.runner import create_run, start_run_async

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
def list_projects(
    q: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ProjectOut]:
    query = db.query(ResearchProject).order_by(ResearchProject.created_at.desc())
    projects = query.all()
    if q:
        needle = q.lower()
        projects = [p for p in projects if needle in p.name.lower() or needle in (p.description or "").lower()]
    return [project_out(p) for p in projects]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProjectOut:
    project = ResearchProject(
        id=new_id("prj"),
        name=body.name.strip(),
        description=body.description.strip(),
        demo_data=body.demo_data,
        created_by=user.id,
        status=ProjectStatus.draft.value,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project_out(project)


@router.post("/sample", response_model=ProjectDetailOut, status_code=201)
def create_sample(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ProjectDetailOut:
    project = create_sample_project(db, user)
    return project_detail_out(project)


@router.get("/{project_id}", response_model=ProjectDetailOut)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProjectDetailOut:
    project = get_project_or_404(db, project_id)
    return project_detail_out(project)


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    body: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProjectOut:
    project = get_project_or_404(db, project_id)
    project.name = body.name.strip()
    project.description = body.description.strip()
    db.commit()
    db.refresh(project)
    return project_out(project)


@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "editor", "doctor")),
) -> dict:
    project = get_project_or_404(db, project_id)
    if project.status == ProjectStatus.processing.value:
        raise bad_request("Cannot delete a project while its pipeline is running.")
    db.delete(project)
    db.commit()
    return {"ok": True, "deleted": project_id}


# --- sources ---------------------------------------------------------------


@router.post("/{project_id}/sources", response_model=SourceOut, status_code=201)
async def upload_source(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SourceOut:
    get_project_or_404(db, project_id)
    source = await ingest.save_upload(project_id, file, db)
    return source_out(source)


@router.post("/{project_id}/sources/reference", response_model=SourceOut, status_code=201)
def add_reference_source(
    project_id: str,
    body: SourceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SourceOut:
    get_project_or_404(db, project_id)
    if body.kind not in {"doi", "url"}:
        raise bad_request("Source kind must be 'doi' or 'url'.")
    if not body.doi and not body.url:
        raise bad_request("Provide a DOI or a URL.")
    source = ingest.add_source_by_reference(
        db, project_id, kind=body.kind, doi=body.doi, url=body.url, title=body.title
    )
    return source_out(source)


@router.delete("/{project_id}/sources/{source_id}")
def remove_source(
    project_id: str,
    source_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    project = get_project_or_404(db, project_id)
    source = next((s for s in project.sources if s.id == source_id), None)
    if source is None:
        raise not_found("Source")
    ingest.remove_source(db, source)
    return {"ok": True, "deleted": source_id}


@router.get("/{project_id}/sources/{source_id}", response_model=SourceDetailOut)
def get_source(
    project_id: str,
    source_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SourceDetailOut:
    project = get_project_or_404(db, project_id)
    source = next((s for s in project.sources if s.id == source_id), None)
    if source is None:
        raise not_found("Source")
    return source_detail_out(source)


# --- pipeline runs ----------------------------------------------------------


@router.post("/{project_id}/run", response_model=PipelineRunOut, status_code=202)
def run_pipeline(
    project_id: str,
    kind: str = "full",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PipelineRunOut:
    project = get_project_or_404(db, project_id)
    if not project.sources:
        raise bad_request("Add at least one source before running the pipeline.")
    if kind not in {"full", "extraction", "generation", "rendering"}:
        raise bad_request("kind must be one of: full, extraction, generation, rendering")
    try:
        run = create_run(db, project, kind)
    except RuntimeError as exc:
        raise bad_request(str(exc)) from exc
    start_run_async(run.id)
    db.refresh(run)
    return pipeline_run_out(run)


@router.get("/{project_id}/runs", response_model=list[PipelineRunOut])
def list_runs(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PipelineRunOut]:
    project = get_project_or_404(db, project_id)
    runs = sorted(project.pipeline_runs, key=lambda r: r.created_at or r.id, reverse=True)
    return [pipeline_run_out(r) for r in runs]
