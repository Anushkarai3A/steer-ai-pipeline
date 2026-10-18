from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.auth import ORMModel

REVIEW_DECISIONS = ["approved", "rejected", "changes_requested"]


class ReviewIn(BaseModel):
    decision: str
    comments: str = Field(default="", max_length=5000)
    version_id: str | None = None

    @field_validator("decision")
    @classmethod
    def valid(cls, v: str) -> str:
        if v not in REVIEW_DECISIONS:
            raise ValueError(f"decision must be one of {REVIEW_DECISIONS}")
        return v


class ReviewOut(ORMModel):
    id: str
    deliverable_id: str
    version_id: str
    version_number: int
    reviewer_id: str | None = None
    reviewer_name: str | None = None
    decision: str
    comments: str
    created_at: datetime | None = None


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    anchor: str | None = Field(default=None, max_length=120)


class CommentOut(ORMModel):
    id: str
    deliverable_id: str
    version_id: str | None = None
    reviewer_id: str | None = None
    reviewer_name: str | None = None
    body: str
    anchor: str | None = None
    resolved: bool = False
    created_at: datetime | None = None


class PublishingItemOut(ORMModel):
    id: str
    deliverable_id: str
    version_id: str
    status: str
    method: str
    note: str
    created_at: datetime | None = None
    published_at: datetime | None = None


class PublishConfirmIn(BaseModel):
    note: str = Field(default="", max_length=2000)
    external_url: str | None = Field(default=None, max_length=1000)


class StageRunOut(ORMModel):
    id: str
    ordinal: int
    stage: str
    label: str
    status: str
    error: str | None = None
    detail: dict = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None


class PipelineRunOut(ORMModel):
    id: str
    project_id: str
    kind: str
    status: str
    mode: str
    pipeline_version: str
    error: str | None = None
    meta: dict = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
    stages: list[StageRunOut] = Field(default_factory=list)
