from __future__ import annotations

import enum

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ProjectStatus(str, enum.Enum):
    draft = "draft"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class SourceStatus(str, enum.Enum):
    uploaded = "uploaded"
    queued = "queued"
    extracting = "extracting"
    extracted = "extracted"
    needs_ocr = "needs_ocr"
    unsupported = "unsupported"
    failed = "failed"


class ResearchProject(Base):
    __tablename__ = "research_projects"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default=ProjectStatus.draft.value)
    demo_data: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(String(40), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[str] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    summary_status: Mapped[str] = mapped_column(String(32), default="pending")

    sources: Mapped[list["ResearchSource"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    claims: Mapped[list["EvidenceClaim"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    deliverables: Mapped[list["ContentDeliverable"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    pipeline_runs: Mapped[list["PipelineRun"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    findings: Mapped[list["ResearchFinding"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ResearchSource(Base):
    __tablename__ = "research_sources"
    __table_args__ = (UniqueConstraint("project_id", "sha256", name="uq_project_source_hash"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), default="pdf")  # pdf | doi | url | demo
    original_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    authors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    journal: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(32), default=SourceStatus.uploaded.value)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[str] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    project: Mapped[ResearchProject] = relationship(back_populates="sources")
    document: Mapped["ExtractedDocument | None"] = relationship(
        back_populates="source", cascade="all, delete-orphan", uselist=False
    )


class ExtractedDocument(Base):
    __tablename__ = "extracted_documents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("research_sources.id", ondelete="CASCADE"), unique=True, index=True
    )
    full_text: Mapped[str] = mapped_column(Text, default="")
    pages: Mapped[list] = mapped_column(JSON, default=list)  # [{"page": 1, "text": "..."}]
    method: Mapped[str] = mapped_column(String(32), default="pymupdf")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    extracted_at: Mapped[str] = mapped_column(DateTime, server_default=func.now())

    source: Mapped[ResearchSource] = relationship(back_populates="document")


class ResearchFinding(Base):
    __tablename__ = "research_findings"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("research_sources.id", ondelete="SET NULL"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(32), default="finding")
    # finding | interpretation | background | recommendation | limitation | conflict
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime, server_default=func.now())

    project: Mapped[ResearchProject] = relationship(back_populates="findings")


class EvidenceClaim(Base):
    __tablename__ = "evidence_claims"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # stable id e.g. CLM-0001
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    claim_text: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(24), default="factual")  # factual | interpretive
    risk_level: Mapped[str] = mapped_column(String(16), default="medium")  # high | medium | low
    population: Mapped[str | None] = mapped_column(Text, nullable=True)
    study_design: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    effect_size: Mapped[str | None] = mapped_column(Text, nullable=True)
    limitations: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="needs_human_review")
    # supported | partially_supported | unsupported | conflicting | needs_human_review
    verification_notes: Mapped[str] = mapped_column(Text, default="")
    #: Source this claim was copied from during extraction. Provenance only —
    #: the authoritative link between a claim and its passages is claim_evidence.
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("research_sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[str] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[str] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    project: Mapped[ResearchProject] = relationship(back_populates="claims")
    evidence: Mapped[list["ClaimEvidence"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", foreign_keys="ClaimEvidence.claim_id"
    )


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("research_sources.id", ondelete="CASCADE"), index=True
    )
    relation: Mapped[str] = mapped_column(String(16), default="supports")  # supports | contradicts | context
    excerpt: Mapped[str] = mapped_column(Text)  # exact text located in the source document
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str | None] = mapped_column(Text, nullable=True)
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    locator_method: Mapped[str] = mapped_column(String(32), default="retrieval")
    created_at: Mapped[str] = mapped_column(DateTime, server_default=func.now())

    claim: Mapped[EvidenceClaim] = relationship(back_populates="evidence")
    source: Mapped[ResearchSource] = relationship()
