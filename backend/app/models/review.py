from __future__ import annotations

import enum

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ReviewDecision(str, enum.Enum):
    approved = "approved"
    rejected = "rejected"
    changes_requested = "changes_requested"


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    deliverable_id: Mapped[str] = mapped_column(
        ForeignKey("content_deliverables.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[str] = mapped_column(ForeignKey("content_versions.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decision: Mapped[str] = mapped_column(String(32))
    comments: Mapped[str] = mapped_column(Text, default="")
    payload_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(DateTime, server_default=func.now())

    deliverable: Mapped["ContentDeliverable"] = relationship(back_populates="reviews")  # noqa: F821
    reviewer: Mapped["User | None"] = relationship(back_populates="reviews")  # noqa: F821


class ReviewComment(Base):
    __tablename__ = "review_comments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    deliverable_id: Mapped[str] = mapped_column(
        ForeignKey("content_deliverables.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_versions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    anchor: Mapped[str | None] = mapped_column(String(120), nullable=True)  # e.g. "slide:3" or "caption"
    resolved: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[str] = mapped_column(DateTime, server_default=func.now())

    deliverable: Mapped["ContentDeliverable"] = relationship(back_populates="comments")  # noqa: F821


class PublishingItem(Base):
    __tablename__ = "publishing_items"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    deliverable_id: Mapped[str] = mapped_column(
        ForeignKey("content_deliverables.id", ondelete="CASCADE"), unique=True, index=True
    )
    version_id: Mapped[str] = mapped_column(ForeignKey("content_versions.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")  # queued | ready_to_publish | published | withdrawn
    method: Mapped[str] = mapped_column(String(32), default="manual_download")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[str] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    published_at: Mapped[str | None] = mapped_column(DateTime, nullable=True)

    deliverable: Mapped["ContentDeliverable"] = relationship(back_populates="publishing_item")  # noqa: F821
