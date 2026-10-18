from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.auth import ORMModel


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)
    demo_data: bool = False


class SourceOut(ORMModel):
    id: str
    project_id: str
    kind: str
    original_filename: str | None = None
    url: str | None = None
    doi: str | None = None
    title: str | None = None
    authors: list | None = None
    year: int | None = None
    journal: str | None = None
    canonical_url: str | None = None
    status: str
    error: str | None = None
    page_count: int | None = None
    char_count: int | None = None
    byte_size: int | None = None
    is_sample: bool = False
    created_at: datetime | None = None


class SourceDetailOut(SourceOut):
    pages: list[dict] = Field(default_factory=list)
    full_text_preview: str = ""
    metadata: dict = Field(default_factory=dict)
    extraction_method: str | None = None


class SourceCreate(BaseModel):
    kind: str = "pdf"  # doi | url
    doi: str | None = None
    url: str | None = None
    title: str | None = None

    @field_validator("doi", "url")
    @classmethod
    def strip_empty(cls, v: str | None) -> str | None:
        return v.strip() if v and v.strip() else None


class ProjectOut(ORMModel):
    id: str
    name: str
    description: str
    status: str
    demo_data: bool
    summary_status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    source_count: int = 0
    claim_count: int = 0
    deliverable_count: int = 0


class ProjectDetailOut(ProjectOut):
    sources: list[SourceOut] = Field(default_factory=list)
    summary: dict | None = None
    findings: list[dict] = Field(default_factory=list)


class FindingOut(BaseModel):
    id: str
    source_id: str | None = None
    category: str
    text: str
    page: int | None = None
    section: str | None = None


class PendingReviewOut(BaseModel):
    deliverable_id: str
    project_id: str
    project_name: str = ""
    format: str
    version_id: str | None = None
    version_number: int | None = None
    status: str
    submitted_at: datetime | None = None


class ClaimStatsOut(BaseModel):
    total: int = 0
    supported: int = 0
    partially_supported: int = 0
    needs_human_review: int = 0
    conflicting: int = 0
    unsupported: int = 0
    high_risk: int = 0


class DashboardStats(BaseModel):
    projects: int = 0
    papers_processed: int = 0
    drafts_generated: int = 0
    awaiting_review: int = 0
    approved_deliverables: int = 0
    failed_jobs: int = 0
    ai_enabled: bool = False
    recent_projects: list[ProjectOut] = Field(default_factory=list)
    recent_activity: list[dict] = Field(default_factory=list)
    pipeline_status: list[dict] = Field(default_factory=list)
    failed_stage_runs: list[dict] = Field(default_factory=list)
    pending_reviews: list[PendingReviewOut] = Field(default_factory=list)
    claim_stats: ClaimStatsOut = Field(default_factory=ClaimStatsOut)
