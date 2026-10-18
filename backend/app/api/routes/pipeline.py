from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.serialize import pipeline_run_out
from app.core.database import get_db
from app.core.errors import bad_request, not_found
from app.models import PipelineRun, User
from app.schemas.review import PipelineRunOut
from app.workers.runner import create_run, start_run_async

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.get("/runs", response_model=list[PipelineRunOut])
def list_runs(
    project_id: str | None = None,
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PipelineRunOut]:
    query = db.query(PipelineRun)
    if project_id:
        query = query.filter(PipelineRun.project_id == project_id)
    runs = query.order_by(PipelineRun.created_at.desc()).limit(min(limit, 100)).all()
    return [pipeline_run_out(r) for r in runs]


@router.get("/runs/{run_id}", response_model=PipelineRunOut)
def get_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> PipelineRunOut:
    run = db.get(PipelineRun, run_id)
    if run is None:
        raise not_found("Pipeline run")
    return pipeline_run_out(run)


@router.post("/runs/{run_id}/retry", response_model=PipelineRunOut, status_code=202)
def retry_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> PipelineRunOut:
    run = db.get(PipelineRun, run_id)
    if run is None:
        raise not_found("Pipeline run")
    if run.status not in {"failed", "succeeded"}:
        raise bad_request("Only finished runs can be retried.")
    from app.models import ResearchProject

    project = db.get(ResearchProject, run.project_id)
    if project is None:
        raise not_found("Project")
    try:
        new = create_run(db, project, run.kind)
    except RuntimeError as exc:
        raise bad_request(str(exc)) from exc
    start_run_async(new.id)
    db.refresh(new)
    return pipeline_run_out(new)
