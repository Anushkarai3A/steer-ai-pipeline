from __future__ import annotations

"""Content generation stage.

Chooses an AI (model-assisted) path or a deterministic fallback based on
environment configuration. AI output is parsed against strict Pydantic schemas
and sanitised (claim ids must exist in the registry; caveats are never allowed
to disappear). If the configured AI provider fails, an LLMError propagates so
the stage fails honestly instead of fabricating success.
"""

import json

from app.models import EvidenceClaim, ResearchProject
from app.services.content_generation import fallback
from app.services.content_generation.llm import LLMError, chat_json, provider_label
from app.services.content_generation.prompt_loader import load_prompt
from app.schemas.content import payload_model_for

FORMAT_PROMPTS = {
    "carousel": "carousel_generation",
    "static": "static_generation",
    "reel": "reel_generation",
    "deck": "deck_generation",
}


def claim_to_dict(claim: EvidenceClaim) -> dict:
    return {
        "id": claim.id,
        "claim_text": claim.claim_text,
        "kind": claim.kind,
        "risk_level": claim.risk_level,
        "population": claim.population,
        "study_design": claim.study_design,
        "outcome": claim.outcome,
        "effect_size": claim.effect_size,
        "limitations": claim.limitations,
        "status": claim.status,
        "verification_notes": claim.verification_notes,
        "evidence": [
            {
                "id": ev.id,
                "source_id": ev.source_id,
                "relation": ev.relation,
                "excerpt": ev.excerpt,
                "page": ev.page,
                "section": ev.section,
                "doi": ev.doi,
                "url": ev.url,
                "source": {
                    "id": ev.source.id,
                    "title": ev.source.title,
                    "journal": ev.source.journal,
                    "year": ev.source.year,
                    "doi": ev.source.doi,
                }
                if ev.source
                else None,
            }
            for ev in claim.evidence
        ],
    }


def _summary_for_prompt(project: ResearchProject) -> dict:
    s = project.summary or {}
    return {
        "research_question": s.get("research_question"),
        "key_findings": s.get("key_findings", [])[:6],
        "study_design": s.get("study_design", []),
        "population": s.get("population", []),
        "limitations": s.get("limitations", [])[:4],
        "conflicts": s.get("conflicts", []),
        "conflict_note": s.get("conflict_note"),
        "not_established": s.get("not_established", []),
    }


def _sources_for(project: ResearchProject) -> list[dict]:
    return [
        {
            "id": s.id,
            "title": s.title,
            "original_filename": s.original_filename,
            "year": s.year,
            "journal": s.journal,
            "doi": s.doi,
            "canonical_url": s.canonical_url,
            "authors": s.authors,
        }
        for s in project.sources
    ]


def _restore_caveats(fmt: str, payload: dict, project: ResearchProject) -> dict:
    """Ensure limitations and disclaimer survive generation."""
    if not payload.get("limitations"):
        summary = project.summary or {}
        limits = [l.get("text") for l in summary.get("limitations", []) if l.get("text")]
        payload["limitations"] = limits[:3] or [
            "Based on the uploaded sources only; a single study set does not settle a topic."
        ]
    if not payload.get("disclaimer"):
        payload["disclaimer"] = fallback.DISCLAIMER
    return payload


def generate_deliverable(
    project: ResearchProject,
    fmt: str,
    claims: list[EvidenceClaim],
    *,
    target: str | None = None,
    target_index: int | None = None,
) -> tuple[dict, dict]:
    """Return (payload, meta). Raises LLMError when AI mode fails."""
    claim_dicts = [claim_to_dict(c) for c in claims]
    valid_ids = {c.id for c in claims}
    sources = _sources_for(project)
    summary = _summary_for_prompt(project)

    meta: dict = {
        "mode": "deterministic",
        "mode_label": fallback.MODE_LABEL,
        "model_name": None,
        "prompt_version": None,
        "provider": provider_label(),
    }

    try:
        if not _ai_enabled():
            raise LLMError("AI provider not configured — using deterministic fallback.")

        prompt_name = FORMAT_PROMPTS[fmt]
        system, prompt_version = load_prompt(prompt_name)
        user = (
            f"Project: {project.name}\n\n"
            f"Research summary (JSON):\n{json.dumps(summary, ensure_ascii=False)}\n\n"
            f"Approved claims (JSON):\n{json.dumps(claim_dicts, ensure_ascii=False)}\n\n"
            f"Source documents (JSON):\n{json.dumps(sources, ensure_ascii=False)}\n\n"
            f"Return ONLY a JSON object matching the {fmt} payload schema."
        )
        raw = chat_json(system, user)
        payload, dropped = _validate_and_scrub(fmt, raw, valid_ids)
        payload = _restore_caveats(fmt, payload, project)
        meta.update({
            "mode": "ai",
            "mode_label": f"Model-assisted generation ({provider_label()})",
            "model_name": provider_label(),
            "prompt_version": prompt_version,
            "dropped_claim_ids": dropped,
        })
        if dropped:
            payload.setdefault("_meta", {})
        return payload, meta

    except LLMError as exc:
        # AI requested but unavailable -> deterministic fallback, clearly labelled.
        payload = _build_deterministic(fmt, project, claims, summary, sources)
        meta["mode"] = "deterministic"
        meta["mode_label"] = fallback.MODE_LABEL + " — AI provider unavailable; fell back to rule-based generation."
        meta["prompt_version"] = None
        meta["ai_error"] = str(exc)
        return payload, meta


def _ai_enabled() -> bool:
    from app.core.config import settings

    return settings.ai_enabled


def _validate_and_scrub(fmt: str, raw: dict, valid_ids: set[str]) -> tuple[dict, list[str]]:
    model_cls = payload_model_for(fmt)
    payload = model_cls.model_validate(raw)
    dropped: list[str] = []

    def scrub(ids: list[str]) -> list[str]:
        keep = []
        for cid in ids:
            (keep if cid in valid_ids else dropped).append(cid)
        return keep

    if fmt == "carousel":
        for slide in payload.slides:
            slide.claim_ids = scrub(slide.claim_ids)
    elif fmt == "static":
        payload.claim_ids = scrub(payload.claim_ids)
    elif fmt == "deck":
        for slide in payload.slides:
            slide.claim_ids = scrub(slide.claim_ids)
    else:
        for scene in payload.scenes:
            scene.claim_ids = scrub(scene.claim_ids)
    return payload.model_dump(), dropped


def _build_deterministic(fmt: str, project: ResearchProject, claims: list[EvidenceClaim], summary: dict, sources: list[dict]) -> dict:
    claim_dicts = [claim_to_dict(c) for c in claims]
    builder = {
        "carousel": fallback.build_carousel,
        "static": fallback.build_static,
        "reel": fallback.build_reel,
        "deck": fallback.build_deck,
    }[fmt]
    try:
        return builder(project.name, summary, claim_dicts, sources)
    except ValueError as exc:
        raise GenerationFallbackError(str(exc)) from exc


class GenerationFallbackError(Exception):
    """Raised when even the deterministic path cannot build content."""


def regenerate_section(
    project: ResearchProject,
    fmt: str,
    claims: list[EvidenceClaim],
    payload: dict,
    *,
    target: str,
    target_index: int | None = None,
) -> tuple[dict, dict]:
    """Regenerate a single section while preserving caveats and scientific meaning."""
    valid_ids = {c.id for c in claims}
    meta: dict = {"mode": "deterministic", "mode_label": fallback.MODE_LABEL, "model_name": None, "prompt_version": None}

    if _ai_enabled():
        try:
            system, prompt_version = load_prompt(FORMAT_PROMPTS[fmt])
            claim_dicts = [claim_to_dict(c) for c in claims]
            user = (
                f"Rewrite ONLY the requested section of this {fmt} content.\n"
                f"Preserve scientific meaning, all claim_ids, limitations and the disclaimer exactly unless "
                f"they are the target. Return ONLY the updated full JSON payload.\n\n"
                f"Target section: {target}" + (f" index {target_index}" if target_index is not None else "") + "\n\n"
                f"Current payload:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
                f"Claims:\n{json.dumps(claim_dicts, ensure_ascii=False)}"
            )
            raw = chat_json(system, user)
            new_payload, dropped = _validate_and_scrub(fmt, raw, valid_ids)
            new_payload = _restore_caveats(fmt, new_payload, project)
            meta.update({"mode": "ai", "mode_label": f"Model-assisted regeneration ({provider_label()})",
                         "model_name": provider_label(), "prompt_version": prompt_version,
                         "dropped_claim_ids": dropped})
            return new_payload, meta
        except LLMError:
            pass

    # Deterministic section regeneration: rotate which linked claim the section presents.
    fresh = _build_deterministic(fmt, project, claims, _summary_for_prompt(project), _sources_for(project))
    if fmt == "deck" and target == "slide" and target_index is not None:
        fresh_slides = fresh.get("slides") or []
        cur_slides = payload.get("slides") or []
        if 0 <= target_index < len(fresh_slides) and 0 <= target_index < len(cur_slides):
            cur_slides[target_index] = fresh_slides[target_index]
            for i, s in enumerate(cur_slides):
                s["index"] = i
            payload["slides"] = cur_slides
            meta["section"] = f"slide:{target_index}"
            meta["mode_label"] = fallback.MODE_LABEL + " — slide rebuilt from linked evidence."
            return payload, meta
        meta["section"] = f"slide:{target_index}"
        meta["mode_label"] = fallback.MODE_LABEL + " — slide index out of range; deck unchanged."
        return payload, meta
    if target in {"caption"} and target in fresh:
        payload["caption"] = fresh["caption"]
        meta["section"] = target
        meta["mode_label"] = fallback.MODE_LABEL + " — section rebuilt from linked evidence."
        return payload, meta
    if target == "slide" and target_index is not None and fmt == "carousel":
        usable = fallback.usable_claims([claim_to_dict(c) for c in claims])
        if usable and payload.get("slides") and 0 <= target_index < len(payload["slides"]):
            candidate = usable[(target_index + 1) % len(usable)]
            slide = payload["slides"][target_index]
            if slide.get("index", target_index) != 0 and slide.get("index", target_index) != len(payload["slides"]) - 1:
                ev = candidate.get("evidence") or [{}]
                slide["headline"] = fallback.shorten(candidate["claim_text"], 90)
                slide["body"] = fallback.shorten(candidate["claim_text"], 240)
                slide["claim_ids"] = [candidate["id"]]
                slide["footnote"] = f"Evidence: {candidate['id']}" + (f" · p. {ev[0].get('page')}" if ev[0].get("page") else "")
                meta["section"] = f"slide:{target_index}"
                meta["mode_label"] = fallback.MODE_LABEL + " — slide rebuilt from linked evidence."
                return payload, meta
        meta["section"] = f"slide:{target_index}"
        meta["mode_label"] = fallback.MODE_LABEL + " — no alternative linked claim available; slide unchanged."
        return payload, meta
    return fresh, meta
