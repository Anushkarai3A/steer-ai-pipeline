from __future__ import annotations

"""Structured-output schemas for model-assisted pipeline stages.

These mirror the JSON schemas exported to pipeline/schemas/. Validation of any
model response happens against these Pydantic models before it is persisted.
"""

from pydantic import BaseModel, Field, field_validator

from app.schemas.content import CarouselPayload, ReelPayload, StaticPayload


class SynthesisEntry(BaseModel):
    text: str = Field(min_length=1)
    source_id: str | None = None
    page: int | None = None
    category: str = "finding"  # finding | interpretation | background | recommendation | limitation | conflict
    section: str | None = None


class ResearchSynthesis(BaseModel):
    research_question: str
    study_design: list[SynthesisEntry] = Field(default_factory=list)
    population: list[SynthesisEntry] = Field(default_factory=list)
    methods: list[SynthesisEntry] = Field(default_factory=list)
    key_findings: list[SynthesisEntry] = Field(default_factory=list)
    numbers: list[SynthesisEntry] = Field(default_factory=list)
    limitations: list[SynthesisEntry] = Field(default_factory=list)
    conflicts: list[SynthesisEntry] = Field(default_factory=list)
    practical_interpretation: list[SynthesisEntry] = Field(default_factory=list)
    not_established: list[SynthesisEntry] = Field(default_factory=list)
    conflict_note: str = ""


class ClaimCandidate(BaseModel):
    claim_text: str = Field(min_length=10, max_length=600)
    kind: str = "factual"
    risk_level: str = "medium"
    population: str | None = None
    study_design: str | None = None
    outcome: str | None = None
    effect_size: str | None = None
    limitations: str | None = None
    source_id: str | None = None
    page: int | None = None

    @field_validator("risk_level")
    @classmethod
    def _risk(cls, v: str) -> str:
        if v not in {"high", "medium", "low"}:
            raise ValueError("risk_level must be high, medium or low")
        return v


class ClaimCandidateList(BaseModel):
    claims: list[ClaimCandidate] = Field(default_factory=list)


class EvidenceAssessment(BaseModel):
    status: str  # supported | partially_supported | unsupported | conflicting | needs_human_review
    verification_notes: str = ""

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        allowed = {"supported", "partially_supported", "unsupported", "conflicting", "needs_human_review"}
        if v not in allowed:
            raise ValueError(f"status must be one of {sorted(allowed)}")
        return v


class SafetyIssue(BaseModel):
    rule: str
    severity: str = "warning"
    message: str
    claim_id: str | None = None
    location: str | None = None

    @field_validator("severity")
    @classmethod
    def _sev(cls, v: str) -> str:
        if v not in {"error", "warning"}:
            raise ValueError("severity must be error or warning")
        return v


class SafetyReview(BaseModel):
    issues: list[SafetyIssue] = Field(default_factory=list)


GENERATION_SCHEMAS: dict[str, type[BaseModel]] = {
    "carousel": CarouselPayload,
    "static": StaticPayload,
    "reel": ReelPayload,
}
