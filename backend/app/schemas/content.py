from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.auth import ORMModel

FORMATS = ["carousel", "static", "reel", "deck"]
DEFAULT_FORMATS = ["carousel", "static", "reel"]


# --- Deliverable payload schemas (validated generation output) ---------------


class Slide(BaseModel):
    index: int
    headline: str = Field(min_length=1, max_length=140)
    body: str = Field(default="", max_length=700)
    claim_ids: list[str] = Field(default_factory=list)
    visual_direction: str = ""
    footnote: str = ""


class SourceNote(BaseModel):
    text: str
    source_id: str | None = None
    doi: str | None = None
    url: str | None = None


class CarouselPayload(BaseModel):
    concept: str = ""
    audience: str = ""
    main_message: str = ""
    slides: list[Slide] = Field(default_factory=list)
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)
    source_notes: list[SourceNote] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    disclaimer: str = ""


class StaticPayload(BaseModel):
    concept: str = ""
    audience: str = ""
    main_message: str = ""
    headline: str = Field(default="", max_length=140)
    body: str = Field(default="", max_length=700)
    claim_ids: list[str] = Field(default_factory=list)
    visual_direction: str = ""
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)
    source_notes: list[SourceNote] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    disclaimer: str = ""


class ReelScene(BaseModel):
    index: int
    start_seconds: float
    end_seconds: float
    on_screen_text: str = ""
    voiceover: str = ""
    visual_direction: str = ""
    claim_ids: list[str] = Field(default_factory=list)


class ReelPayload(BaseModel):
    concept: str = ""
    audience: str = ""
    main_message: str = ""
    duration_seconds: int = Field(default=45, ge=10, le=120)
    hook: str = ""
    scenes: list[ReelScene] = Field(default_factory=list)
    on_screen_captions: bool = True
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)
    source_notes: list[SourceNote] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    disclaimer: str = ""
    closing_takeaway: str = ""

    @field_validator("scenes")
    @classmethod
    def scenes_ordered(cls, v: list[ReelScene]) -> list[ReelScene]:
        for i, s in enumerate(v):
            if s.index != i:
                raise ValueError("scene indexes must be sequential from 0")
        return v


class DeckTable(BaseModel):
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class DeckSlide(BaseModel):
    index: int
    kind: str = Field(default="content", max_length=40)  # title | background | methods | population | findings | quantitative | interpretation | limitations | takeaways | references | content
    title: str = Field(min_length=1, max_length=160)
    bullets: list[str] = Field(default_factory=list)
    table: DeckTable | None = None
    claim_ids: list[str] = Field(default_factory=list)
    source_notes: list[str] = Field(default_factory=list)


class DeckPayload(BaseModel):
    concept: str = ""
    audience: str = ""
    main_message: str = ""
    deck_title: str = Field(default="", max_length=200)
    subtitle: str = Field(default="", max_length=300)
    slides: list[DeckSlide] = Field(default_factory=list)
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)
    source_notes: list[SourceNote] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    disclaimer: str = ""

    @field_validator("slides")
    @classmethod
    def slides_ordered(cls, v: list[DeckSlide]) -> list[DeckSlide]:
        for i, s in enumerate(v):
            if s.index != i:
                raise ValueError("deck slide indexes must be sequential from 0")
        return v


def payload_model_for(fmt: str) -> type[BaseModel]:
    return {
        "carousel": CarouselPayload,
        "static": StaticPayload,
        "reel": ReelPayload,
        "deck": DeckPayload,
    }[fmt]


# --- Deliverable DTOs --------------------------------------------------------


class AssetOut(ORMModel):
    id: str
    kind: str
    filename: str
    mime: str
    byte_size: int | None = None
    label: str | None = None
    created_at: datetime | None = None


class ValidationIssue(BaseModel):
    rule: str
    severity: str  # error | warning
    message: str
    claim_id: str | None = None
    location: str | None = None


class VersionOut(ORMModel):
    id: str
    deliverable_id: str
    version_number: int
    payload: dict = Field(default_factory=dict)
    generation_mode: str
    generation_mode_label: str
    model_name: str | None = None
    prompt_version: str | None = None
    material_hash: str = ""
    validation: dict = Field(default_factory=dict)
    validation_status: str = "pending"
    created_at: datetime | None = None
    assets: list[AssetOut] = Field(default_factory=list)

    @property
    def label(self) -> str:
        return f"v{self.version_number}"


class DeliverableOut(ORMModel):
    id: str
    project_id: str
    format: str
    concept: str
    audience: str
    main_message: str
    status: str
    current_version_id: str | None = None
    approved_version_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DeliverableDetailOut(DeliverableOut):
    versions: list[VersionOut] = Field(default_factory=list)
    current_version: VersionOut | None = None
    comments: list[dict] = Field(default_factory=list)
    reviews: list[dict] = Field(default_factory=list)
    publishing_item: dict | None = None
    blocked_claims: list[str] = Field(default_factory=list)


class GenerateIn(BaseModel):
    formats: list[str] = Field(default_factory=lambda: list(DEFAULT_FORMATS))

    @field_validator("formats")
    @classmethod
    def valid_formats(cls, v: list[str]) -> list[str]:
        bad = [f for f in v if f not in FORMATS]
        if bad:
            raise ValueError(f"unknown formats: {bad}")
        if not v:
            raise ValueError("at least one format is required")
        return v


class EditVersionIn(BaseModel):
    payload: dict
    note: str = Field(default="", max_length=500)


class SubmitForReviewIn(BaseModel):
    note: str = Field(default="", max_length=1000)
