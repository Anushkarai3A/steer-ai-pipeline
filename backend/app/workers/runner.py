from __future__ import annotations

"""Pipeline runner: executes stages with real state, honest errors and retries.

Jobs run in a background thread pool (no Redis required for local development).
Every stage transition is persisted to pipeline_stage_runs so the UI can show
real status instead of fake progress. A failed run can be retried — stages are
idempotent, so completed work is reused.
"""

import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.ids import new_id
from app.models import PIPELINE_STAGES, PipelineRun, PipelineStageRun, ProjectStatus, ResearchProject
from app.workers.stages import STAGE_FUNCTIONS, StageError

logger = logging.getLogger("steer.pipeline")

STAGE_PLANS: dict[str, list[str]] = {
    "full": [s for s, _ in PIPELINE_STAGES],
    "extraction": ["ingestion", "extraction", "metadata", "synthesis", "claims", "evidence", "doctor_review"],
    "generation": ["content", "validation", "rendering", "doctor_review"],
    "rendering": ["rendering", "doctor_review"],
}

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="steer-pipeline")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_run(db: Session, project: ResearchProject, kind: str = "full") -> PipelineRun:
    if kind not in STAGE_PLANS:
        raise ValueError(f"Unknown pipeline kind: {kind}")
    if project.status == ProjectStatus.processing.value:
        raise RuntimeError("A pipeline run is already in progress for this project.")

    run = PipelineRun(
        id=new_id("run"),
        project_id=project.id,
        kind=kind,
        status="queued",
        mode="ai" if settings.ai_enabled else "deterministic",
        pipeline_version=settings.pipeline_version,
        meta={"provider": "ai-enabled" if settings.ai_enabled else "deterministic-fallback"},
    )
    db.add(run)
    stages = STAGE_PLANS[kind]
    labels = dict(PIPELINE_STAGES)
    for i, stage_name in enumerate(stages):
        db.add(
            PipelineStageRun(
                id=new_id("stg"),
                run_id=run.id,
                ordinal=i,
                stage=stage_name,
                label=labels[stage_name],
                status="pending",
            )
        )
    project.status = ProjectStatus.processing.value
    db.commit()
    db.refresh(run)
    return run


def start_run_async(run_id: str) -> None:
    _executor.submit(_run_thread, run_id)


def _run_thread(run_id: str) -> None:  # pragma: no cover - exercised via sync path in tests
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        execute_run(db, run_id)
    except Exception:
        logger.error("Pipeline run %s crashed:\n%s", run_id, traceback.format_exc())
    finally:
        db.close()


def execute_run(db: Session, run_id: str) -> PipelineRun:
    run = db.get(PipelineRun, run_id)
    if run is None:
        raise ValueError(f"Pipeline run {run_id} not found")
    project = db.get(ResearchProject, run.project_id)
    if project is None:
        raise ValueError("Project missing for pipeline run")

    run.status = "running"
    run.started_at = _now()
    db.commit()

    failed_stage_label: str | None = None
    for stage in sorted(run.stages, key=lambda s: s.ordinal):
        if failed_stage_label is not None:
            stage.status = "skipped"
            stage.detail = {"reason": f"Not run because stage '{failed_stage_label}' failed."}
            db.commit()
            continue

        fn = STAGE_FUNCTIONS.get(stage.stage)
        if fn is None:
            stage.status = "failed"
            stage.error = f"No implementation registered for stage '{stage.stage}'."
            failed_stage_label = stage.label
            db.commit()
            continue

        stage.status = "running"
        stage.started_at = _now()
        db.commit()
        try:
            detail = fn(db, project, run)
        except StageError as exc:
            db.rollback()  # discard any partial writes made by the failed stage
            stage.status = "failed"
            stage.error = str(exc)
            stage.finished_at = _now()
            stage.duration_ms = _ms(stage.started_at, stage.finished_at)
            failed_stage_label = stage.label
            db.commit()
        except Exception as exc:
            logger.error("Stage %s crashed:\n%s", stage.stage, traceback.format_exc())
            db.rollback()
            stage.status = "failed"
            stage.error = f"Unexpected error in stage '{stage.label}': {exc}"
            stage.finished_at = _now()
            stage.duration_ms = _ms(stage.started_at, stage.finished_at)
            failed_stage_label = stage.label
            db.commit()
        else:
            stage.finished_at = _now()
            stage.duration_ms = _ms(stage.started_at, stage.finished_at)
            if isinstance(detail, dict) and detail.get("status") == "pending":
                stage.status = "pending"
                stage.detail = {k: v for k, v in detail.items() if k != "status"}
            else:
                stage.status = "succeeded"
                stage.detail = detail or {}
            db.commit()

    run.finished_at = _now()
    if failed_stage_label:
        run.status = "failed"
        failed_stage = next(
            (s for s in run.stages if s.label == failed_stage_label and s.status == "failed"), None
        )
        run.error = (
            f"Stage '{failed_stage_label}' failed: {failed_stage.error if failed_stage else 'unknown error'}"
        )
        project.status = ProjectStatus.failed.value
    else:
        run.status = "succeeded"
        project.status = ProjectStatus.ready.value
    db.commit()
    db.refresh(run)
    return run


def _ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    # SQLite returns naive datetimes; treat them as UTC.
    from datetime import timezone as _tz

    if start.tzinfo is None:
        start = start.replace(tzinfo=_tz.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=_tz.utc)
    return int((end - start).total_seconds() * 1000)
