from __future__ import annotations

import enum

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class DeliverableFormat(str, enum.Enum):
    carousel = "carousel"
    static = "static"
    reel = "reel"
    deck = "deck"


class DeliverableStatus(str, enum.Enum):
    draft = "draft"
    processing = "processing"
    needs_evidence_review = "needs_evidence_review"
    awaiting_review = "awaiting_review"
    changes_requested = "changes_requested"
    rejected = "rejected"
    approved = "approved"
    ready_to_publish = "ready_to_publish"
    published = "published"


class ContentDeliverable(Base):
    __tablename__ = "content_deliverables"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    format: Mapped[str] = mapped_column(String(16), index=True)
    concept: Mapped[str] = mapped_column(Text, default="")
    audience: Mapped[str] = mapped_column(Text, default="")
    main_message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default=DeliverableStatus.draft.value, index=True)
    current_version_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    approved_version_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[str] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    project: Mapped["ResearchProject"] = relationship(back_populates="deliverables")  # noqa: F821
    versions: Mapped[list["ContentVersion"]] = relationship(
        back_populates="deliverable",
        cascade="all, delete-orphan",
        order_by="ContentVersion.version_number",
        foreign_keys="ContentVersion.deliverable_id",
    )
    reviews: Mapped[list["Review"]] = relationship(  # noqa: F821
        back_populates="deliverable", cascade="all, delete-orphan"
    )
    comments: Mapped[list["ReviewComment"]] = relationship(  # noqa: F821
        back_populates="deliverable", cascade="all, delete-orphan"
    )
    publishing_item: Mapped["PublishingItem | None"] = relationship(  # noqa: F821
        back_populates="deliverable", cascade="all, delete-orphan", uselist=False
    )

    @property
    def current_version(self) -> "ContentVersion | None":
        if not self.current_version_id:
            return None
        return next((v for v in self.versions if v.id == self.current_version_id), None)


class ContentVersion(Base):
    __tablename__ = "content_versions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    deliverable_id: Mapped[str] = mapped_column(
        ForeignKey("content_deliverables.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    generation_mode: Mapped[str] = mapped_column(String(24), default="deterministic")
    # ai | deterministic
    generation_mode_label: Mapped[str] = mapped_column(String(64), default="Deterministic demo generator")
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    material_hash: Mapped[str] = mapped_column(String(64), default="")
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    validation_status: Mapped[str] = mapped_column(String(32), default="pending")
    # pending | passed | warnings | failed
    created_at: Mapped[str] = mapped_column(DateTime, server_default=func.now())

    deliverable: Mapped[ContentDeliverable] = relationship(back_populates="versions")
    assets: Mapped[list["ContentAsset"]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )

    @property
    def number_label(self) -> str:
        return f"v{self.version_number}"


class ContentAsset(Base):
    __tablename__ = "content_assets"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("content_versions.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))  # carousel_slide | carousel_zip | static_png | reel_mp4 | storyboard
    file_path: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(512))
    mime: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime, server_default=func.now())

    version: Mapped[ContentVersion] = relationship(back_populates="assets")
