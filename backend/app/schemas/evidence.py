from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.auth import ORMModel

CLAIM_STATUSES = [
    "supported",
    "partially_supported",
    "unsupported",
    "conflicting",
    "needs_human_review",
]


class EvidenceOut(ORMModel):
    id: str
    claim_id: str
    source_id: str
    relation: str
    excerpt: str
    page: int | None = None
    section: str | None = None
    doi: str | None = None
    url: str | None = None
    locator_method: str
    source_title: str | None = None
    source_filename: str | None = None
    source_year: int | None = None
    source_journal: str | None = None


class ClaimOut(ORMModel):
    id: str
    project_id: str
    claim_text: str
    kind: str
    risk_level: str
    population: str | None = None
    study_design: str | None = None
    outcome: str | None = None
    effect_size: str | None = None
    limitations: str | None = None
    status: str
    verification_notes: str = ""
    created_at: datetime | None = None
    evidence: list[EvidenceOut] = Field(default_factory=list)


class ClaimUpdate(BaseModel):
    status: str | None = None
    verification_notes: str | None = None
    claim_text: str | None = None
    limitations: str | None = None

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str | None) -> str | None:
        if v is not None and v not in CLAIM_STATUSES:
            raise ValueError(f"status must be one of {CLAIM_STATUSES}")
        return v


class SourceExcerptOut(BaseModel):
    source_id: str
    title: str | None = None
    page: int | None = None
    section: str | None = None
    excerpt: str
    surrounding_text: str = ""
    doi: str | None = None
    url: str | None = None
