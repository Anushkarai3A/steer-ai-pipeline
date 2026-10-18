from __future__ import annotations

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

PIPELINE_STAGES = [
    ("ingestion", "Source ingestion"),
    ("extraction", "Text extraction"),
    ("metadata", "Metadata extraction"),
    ("synthesis", "Research synthesis"),
    ("claims", "Claim extraction"),
    ("evidence", "Evidence linking"),
    ("content", "Content generation"),
    ("validation", "Validation"),
    ("rendering", "Asset rendering"),
    ("doctor_review", "Doctor review"),
]


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32), default="full")  # full | extraction | generation | rendering
    status: Mapped[str] = mapped_column(String(32), default="queued")  # queued | running | succeeded | failed
    mode: Mapped[str] = mapped_column(String(24), default="deterministic")  # ai | deterministic
    pipeline_version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[str | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime, server_default=func.now())

    project: Mapped["ResearchProject"] = relationship(back_populates="pipeline_runs")  # noqa: F821
    stages: Mapped[list["PipelineStageRun"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="PipelineStageRun.ordinal",
    )


class PipelineStageRun(Base):
    __tablename__ = "pipeline_stage_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[str] = mapped_column(String(48))  # machine name
    label: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    # pending | running | succeeded | failed | skipped
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[str | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    run: Mapped[PipelineRun] = relationship(back_populates="stages")
