from __future__ import annotations

"""Pipeline stage implementations (explicit, observable, testable).

Each stage either returns a detail dict for the UI or raises StageError with a
human-readable, actionable message. Stages never report success for work that
did not happen, and never fabricate metadata or evidence.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    ContentDeliverable,
    ContentVersion,
    EvidenceClaim,
    ExtractedDocument,
    PipelineRun,
    ProjectStatus,
    ResearchProject,
    ResearchSource,
    SourceStatus,
)
from app.core.ids import new_id
from app.services.claims.evidence_link import verify_claim
from app.services.claims.extract import extract_claims_deterministic
from app.services.content_generation.generate import GenerationFallbackError, generate_deliverable
from app.services.extraction.metadata_enrich import crossref_lookup, fetch_public_pdf
from app.services.extraction.pdf_extractor import ExtractionError, extract_pdf
from app.services.rendering.render_assets import RenderError, render_version_assets
from app.services.research.synthesis import persist_findings, synthesize_deterministic
from app.services.review.workflow import material_hash, sync_publishing_item
from app.services.validation.validate import validate_payload


class StageError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _next_claim_index(db: Session) -> int:
    """Next free CLM-#### index across the whole registry (ids are global)."""
    import re

    rows = db.query(EvidenceClaim.id).all()
    used = set()
    for (cid,) in rows:
        m = re.fullmatch(r"CLM-(\d+)", cid or "")
        if m:
            used.add(int(m.group(1)))
    idx = 1
    while idx in used:
        idx += 1
    return idx


def stage_ingestion(db: Session, project: ResearchProject, run: PipelineRun) -> dict:
    sources = project.sources
    if not sources:
        raise StageError("No sources in this project. Upload 1–3 PDFs (or add a DOI/URL) and run again.")
    if len(sources) > settings.max_sources_per_project:
        raise StageError(f"Project has {len(sources)} sources; the maximum is {settings.max_sources_per_project}.")
    for s in sources:
        if s.kind == "pdf" and (not s.file_path or not s.sha256):
            raise StageError(f"Source '{s.original_filename or s.id}' has no stored file. Re-upload it.")
    return {
        "sources": [
            {"id": s.id, "filename": s.original_filename, "title": s.title, "kind": s.kind, "status": s.status}
            for s in sources
        ],
        "count": len(sources),
    }


def stage_extraction(db: Session, project: ResearchProject, run: PipelineRun) -> dict:
    extracted, skipped, failed = [], [], []
    for source in project.sources:
        if source.document is not None and source.status == SourceStatus.extracted.value:
            skipped.append(source.id)
            continue
        try:
            if source.kind == "pdf":
                _extract_pdf_source(db, source)
            else:
                _extract_reference_source(db, source)
        except ExtractionError as exc:
            source.status = (
                SourceStatus.needs_ocr.value if "scanned" in str(exc).lower()
                else SourceStatus.unsupported.value if "ocr" in str(exc).lower() or "text" in str(exc).lower()
                else SourceStatus.failed.value
            )
            source.error = str(exc)
            failed.append({"id": source.id, "status": source.status, "error": str(exc)})
        except Exception as exc:  # unexpected but must be reported, never swallowed
            source.status = SourceStatus.failed.value
            source.error = f"Unexpected extraction error: {exc}"
            failed.append({"id": source.id, "status": source.status, "error": source.error})
        db.commit()

    db.refresh(project)
    extracted_now = [s.id for s in project.sources if s.status == SourceStatus.extracted.value]
    if not extracted_now:
        details = "; ".join(f"{f['id']}: {f['error']}" for f in failed) or "no sources"
        raise StageError(f"No source produced extractable text. {details}")

    detail = {"extracted": extracted_now, "skipped": skipped, "failed": failed}
    if failed:
        detail["warning"] = (
            f"{len(failed)} source(s) could not be extracted; the pipeline continued with "
            f"{len(extracted_now)} source(s). Fix or remove the failed source(s) and re-run."
        )
    return detail


def _extract_pdf_source(db: Session, source: ResearchSource) -> None:
    source.status = SourceStatus.extracting.value
    db.commit()
    result = extract_pdf(source.file_path or "")
    _store_extraction(db, source, result)


def _extract_reference_source(db: Session, source: ResearchSource) -> None:
    """Resolve a DOI/URL reference: metadata via Crossref; PDF only when openly available."""
    meta = None
    if source.kind == "doi" and source.doi:
        meta = crossref_lookup(source.doi)
        if meta:
            source.canonical_url = source.canonical_url or meta.get("url")

    pdf_url = None
    if meta and meta.get("pdf_url"):
        pdf_url = meta["pdf_url"]
    elif source.kind == "url" and (source.url or "").lower().split("?")[0].endswith(".pdf"):
        pdf_url = source.url

    if pdf_url:
        data = fetch_public_pdf(pdf_url)
        if data:
            import hashlib as _hashlib

            sha = _hashlib.sha256(data).hexdigest()
            source.sha256 = sha
            dest_dir = settings.upload_path / source.project_id
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{source.id}.pdf"
            dest.write_bytes(data)
            source.file_path = str(dest)
            source.byte_size = len(data)
            source.kind = "pdf" if source.kind == "doi" else source.kind
            source.original_filename = source.original_filename or f"{source.doi or 'source'}.pdf"
            try:
                result = extract_pdf(dest)
            except ExtractionError as exc:
                source.status = SourceStatus.failed.value
                source.error = str(exc)
                db.commit()
                return
            _store_extraction(db, source, result)
            if meta:
                _apply_crossref(source, meta)
            return

    # No openly accessible full text — record real metadata, never fake content.
    if meta:
        _apply_crossref(source, meta)
        source.status = SourceStatus.unsupported.value
        source.error = (
            "Metadata resolved from Crossref, but no openly accessible full text was available "
            "and this app does not bypass paywalls. Upload the PDF to include this source's text."
        )
    else:
        source.status = SourceStatus.unsupported.value
        source.error = (
            "Could not resolve this reference (DOI lookup failed or network unavailable) and no "
            "PDF was provided. Upload the PDF file to include this source."
        )
    db.commit()


def _apply_crossref(source: ResearchSource, meta: dict) -> None:
    source.title = source.title if (source.title and not _looks_like_filename(source.title)) else (meta.get("title") or source.title)
    if meta.get("authors"):
        source.authors = meta["authors"]
    if meta.get("year"):
        source.year = meta["year"]
    if meta.get("journal"):
        source.journal = meta["journal"]
    if meta.get("doi"):
        source.doi = meta["doi"]
    if meta.get("url"):
        source.canonical_url = source.canonical_url or meta["url"]


def _looks_like_filename(value: str) -> bool:
    return value.lower().endswith(".pdf") or "_" in value or "-" in value


def _store_extraction(db: Session, source: ResearchSource, result: dict) -> None:
    if not result.get("full_text", "").strip():
        source.status = SourceStatus.failed.value
        source.error = "Extraction produced empty text."
        db.commit()
        return
    if source.document:
        doc = source.document
        doc.full_text = result["full_text"]
        doc.pages = result["pages"]
        doc.method = result["method"]
        doc.metadata_json = result.get("metadata", {})
    else:
        doc = ExtractedDocument(
            id=new_id("doc"),
            source_id=source.id,
            full_text=result["full_text"],
            pages=result["pages"],
            method=result["method"],
            metadata_json=result.get("metadata", {}),
        )
        db.add(doc)
    md = result.get("metadata", {})
    source.page_count = result["page_count"]
    source.char_count = len(result["full_text"])
    source.status = SourceStatus.extracted.value
    source.error = None
    if md.get("pdf_title"):
        source.title = md["pdf_title"]
    if md.get("pdf_author") and not source.authors:
        source.authors = [a.strip() for a in str(md["pdf_author"]).split(";") if a.strip()]
    if md.get("year") and not source.year:
        source.year = md["year"]
    if md.get("doi") and not source.doi:
        source.doi = md["doi"]
    if source.doi and not source.canonical_url:
        source.canonical_url = f"https://doi.org/{source.doi}"
    db.commit()


def stage_metadata(db: Session, project: ResearchProject, run: PipelineRun) -> dict:
    enriched, unresolved = [], []
    for source in project.sources:
        if source.doi and (not source.title or not source.journal or not source.year):
            meta = crossref_lookup(source.doi)
            if meta:
                _apply_crossref(source, meta)
                enriched.append(source.id)
        if source.document and not source.title:
            md = source.document.metadata_json or {}
            if md.get("pdf_title"):
                source.title = md["pdf_title"]
        if not source.title:
            unresolved.append(source.id)
    db.commit()
    return {
        "enriched": enriched,
        "unresolved_metadata": unresolved,
        "note": "Fields that could not be determined are left empty (shown as 'Unavailable'), never invented.",
    }


def stage_synthesis(db: Session, project: ResearchProject, run: PipelineRun) -> dict:
    extracted_sources = [s for s in project.sources if s.document and s.document.full_text.strip()]
    if not extracted_sources:
        raise StageError("No extracted source text available for synthesis. Fix extraction first.")
    summary = synthesize_deterministic(db, project)
    project.summary = summary
    project.summary_status = "ready"
    findings = persist_findings(db, project, summary)
    db.commit()
    return {
        "mode": summary["mode"],
        "mode_label": summary["mode_label"],
        "findings_recorded": findings,
        "excluded_sources": summary.get("excluded_sources", []),
        "key_findings": len(summary.get("key_findings", [])),
        "limitations": len(summary.get("limitations", [])),
    }


def stage_claims(db: Session, project: ResearchProject, run: PipelineRun) -> dict:
    summary = project.summary
    if not summary:
        raise StageError("Research summary missing — run synthesis before claim extraction.")
    candidates = extract_claims_deterministic(project, summary)
    if not candidates:
        raise StageError(
            "No candidate claims could be extracted from the source text. "
            "Check that the sources contain results with measurable findings."
        )
    db.query(EvidenceClaim).filter(EvidenceClaim.project_id == project.id).delete()
    db.flush()
    start = _next_claim_index(db)
    for i, c in enumerate(candidates):
        db.add(
            EvidenceClaim(
                id=f"CLM-{start + i:04d}",
                project_id=project.id,
                claim_text=c["claim_text"],
                kind=c.get("kind", "factual"),
                risk_level=c.get("risk_level", "medium"),
                population=c.get("population"),
                study_design=c.get("study_design"),
                outcome=c.get("outcome"),
                effect_size=c.get("effect_size"),
                limitations=c.get("limitations"),
                status="needs_human_review",
                source_id=c.get("candidate_source_id"),
                verification_notes=(
                    "Candidate claim extracted with rule-based verbatim sentence selection. "
                    "Evidence linking runs in the next stage; status is set there."
                ),
            )
        )
    db.commit()
    return {
        "claims_extracted": len(candidates),
        "method": "verbatim_sentence (rule-based)",
        "note": "Claims are verbatim sentences from the stored sources at this point; statuses are set by evidence linking.",
    }


def stage_evidence(db: Session, project: ResearchProject, run: PipelineRun) -> dict:
    claims = sorted(project.claims, key=lambda c: c.id)
    if not claims:
        raise StageError("No claims to verify. Run claim extraction first.")
    summary: dict[str, int] = {}
    for claim in claims:
        # Prefer the source the claim was copied from: a verbatim sentence is
        # genuine evidence in its own paper, and stops unrelated papers that
        # share generic wording from being attached instead.
        verify_claim(db, project, claim, preferred_source_id=claim.source_id)
        summary[claim.status] = summary.get(claim.status, 0) + 1
        db.commit()
    return {
        "verified": len(claims),
        "status_counts": summary,
        "note": "Statuses reflect mechanically located passages; they are not a clinical fact-check.",
    }


def stage_content(db: Session, project: ResearchProject, run: PipelineRun) -> dict:
    if not project.summary:
        raise StageError("Research summary missing — run synthesis before content generation.")
    claims = sorted(project.claims, key=lambda c: c.id)
    if not claims:
        raise StageError("No claims available for content generation.")

    created, skipped = [], []
    requested = (run.meta or {}).get("formats") or ["carousel", "static", "reel"]
    for fmt in ("carousel", "static", "reel", "deck"):
        if fmt not in requested:
            continue
        deliverable = next((d for d in project.deliverables if d.format == fmt), None)
        if deliverable and deliverable.current_version_id:
            skipped.append({"format": fmt, "reason": "already generated — use Regenerate to create a new version"})
            continue
        if deliverable is None:
            deliverable = ContentDeliverable(
                id=new_id("dlv"), project_id=project.id, format=fmt, status="processing"
            )
            db.add(deliverable)
            db.flush()
        try:
            payload, meta = generate_deliverable(project, fmt, claims)
        except GenerationFallbackError as exc:
            deliverable.status = "draft"
            db.commit()
            raise StageError(str(exc)) from exc
        except Exception as exc:  # LLM failures surfaced honestly
            deliverable.status = "draft"
            db.commit()
            raise StageError(f"Content generation failed for {fmt}: {exc}") from exc

        payload["_generation"] = meta
        version = ContentVersion(
            id=new_id("cv"),
            deliverable_id=deliverable.id,
            version_number=1,
            payload=payload,
            generation_mode=meta.get("mode", "deterministic"),
            generation_mode_label=meta.get("mode_label", ""),
            model_name=meta.get("model_name"),
            prompt_version=meta.get("prompt_version"),
            material_hash=material_hash(payload),
            validation={},
            validation_status="pending",
        )
        db.add(version)
        db.flush()
        deliverable.current_version_id = version.id
        deliverable.concept = payload.get("concept", "")
        deliverable.audience = payload.get("audience", "")
        deliverable.main_message = payload.get("main_message", "")
        deliverable.status = "draft"
        created.append({"format": fmt, "version": version.version_number, "mode": meta.get("mode")})
        db.commit()

    db.expire(project, ["deliverables"])
    return {
        "created": created,
        "skipped": skipped,
        "mode": created[0]["mode"] if created else "unchanged",
        "mode_label": (payload_meta_label(project) if created else "existing versions kept"),
    }


def payload_meta_label(project: ResearchProject) -> str:
    for d in project.deliverables:
        v = d.current_version
        if v and v.generation_mode_label:
            return v.generation_mode_label
    return ""


def stage_validation(db: Session, project: ResearchProject, run: PipelineRun) -> dict:
    db.expire(project, ["deliverables"])
    claims_by_id = {c.id: c for c in project.claims}
    results = []
    for deliverable in project.deliverables:
        version = deliverable.current_version
        if version is None:
            continue
        validation = validate_payload(deliverable.format, version.payload, project, claims_by_id)
        version.validation = validation
        version.validation_status = validation["status"]
        if validation["status"] == "failed" and deliverable.status in {"draft", "processing"}:
            deliverable.status = "needs_evidence_review"
        elif validation["status"] != "failed" and deliverable.status == "needs_evidence_review":
            deliverable.status = "draft"
        results.append({
            "format": deliverable.format,
            "status": validation["status"],
            "errors": validation["counts"]["errors"],
            "warnings": validation["counts"]["warnings"],
        })
        db.commit()
        sync_publishing_item(db, deliverable)
        db.commit()
    return {"results": results, "rules_version": "deterministic_rules_v1"}


def stage_rendering(db: Session, project: ResearchProject, run: PipelineRun) -> dict:
    db.expire(project, ["deliverables"])
    rendered, failed = [], []
    for deliverable in project.deliverables:
        version = deliverable.current_version
        if version is None:
            continue
        version_dir = settings.generated_path / version.id
        try:
            asset_specs = render_version_assets(deliverable.format, version.payload, version_dir)
        except RenderError as exc:
            failed.append({"format": deliverable.format, "error": str(exc)})
            continue
        except Exception as exc:
            failed.append({"format": deliverable.format, "error": f"Rendering error: {exc}"})
            continue
        _replace_assets(db, version, asset_specs)
        rendered.append({
            "format": deliverable.format,
            "assets": len(asset_specs),
            "version": version.version_number,
        })
        db.commit()

    if failed and not rendered:
        raise StageError("Asset rendering failed: " + "; ".join(f"{f['format']}: {f['error']}" for f in failed))
    detail: dict = {"rendered": rendered, "failed": failed}
    if failed:
        detail["warning"] = "Some formats failed to render: " + "; ".join(
            f"{f['format']}: {f['error']}" for f in failed
        )
    return detail


def _replace_assets(db: Session, version: ContentVersion, asset_specs: list[dict]) -> None:
    from app.models import ContentAsset

    for old in list(version.assets):
        db.delete(old)
    db.flush()
    for spec in asset_specs:
        from pathlib import Path

        p = Path(spec["path"])
        db.add(
            ContentAsset(
                id=new_id("ast"),
                version_id=version.id,
                kind=spec["kind"],
                file_path=spec["path"],
                filename=spec["filename"],
                mime=spec["mime"],
                byte_size=p.stat().st_size if p.exists() else None,
                label=spec.get("label"),
            )
        )


def stage_doctor_review(db: Session, project: ResearchProject, run: PipelineRun) -> dict:
    pending = [d for d in project.deliverables if d.status in {"draft", "needs_evidence_review", "awaiting_review"}]
    return {
        "status": "pending",
        "awaiting_action": [
            {"id": d.id, "format": d.format, "status": d.status} for d in pending
        ],
        "message": (
            "Doctor review is a human step and is never marked complete automatically. "
            "Submit deliverables for review from the Content Studio."
        ),
    }


STAGE_FUNCTIONS = {
    "ingestion": stage_ingestion,
    "extraction": stage_extraction,
    "metadata": stage_metadata,
    "synthesis": stage_synthesis,
    "claims": stage_claims,
    "evidence": stage_evidence,
    "content": stage_content,
    "validation": stage_validation,
    "rendering": stage_rendering,
    "doctor_review": stage_doctor_review,
}
