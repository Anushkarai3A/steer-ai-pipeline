from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_project_or_404, require_roles
from app.api.serialize import deliverable_detail_out, deliverable_out
from app.core.config import settings
from app.core.database import get_db
from app.core.errors import bad_request, conflict, not_found
from app.core.ids import new_id
from app.models import ContentAsset, ContentDeliverable, ContentVersion, User
from app.schemas.content import DeliverableDetailOut, DeliverableOut, EditVersionIn, SubmitForReviewIn
from pydantic import BaseModel, Field


class GenerateBody(BaseModel):
    formats: list[str] = Field(default_factory=lambda: ["carousel", "static", "reel"])


EXPORT_KINDS = {"full", "evidence_report", "source_manifest", "captions"}


class ExportIn(BaseModel):
    kind: str = "full"
from app.services.content_generation.generate import GenerationFallbackError, generate_deliverable, regenerate_section
from app.services.review.workflow import add_comment, apply_edit, material_hash, submit_for_review, sync_publishing_item
from app.services.validation.validate import has_blocking_errors, validate_payload
from app.workers.runner import create_run, start_run_async
from app.schemas.review import PipelineRunOut
from app.api.serialize import pipeline_run_out

router = APIRouter(prefix="/api", tags=["content"])


def _get_deliverable(db: Session, deliverable_id: str) -> ContentDeliverable:
    d = db.get(ContentDeliverable, deliverable_id)
    if d is None:
        raise not_found("Deliverable")
    return d


def _blocked_claims(d: ContentDeliverable) -> list[str]:
    v = d.current_version
    if not v or not v.validation:
        return []
    return sorted({
        i["claim_id"]
        for i in v.validation.get("issues", [])
        if i.get("severity") == "error" and i.get("claim_id")
    })


def _revalidate(db: Session, d: ContentDeliverable) -> None:
    project = d.project
    version = d.current_version
    if version is None:
        return
    validation = validate_payload(d.format, version.payload, project, {c.id: c for c in project.claims})
    version.validation = validation
    version.validation_status = validation["status"]
    if validation["status"] == "failed" and d.status in {"draft", "processing"}:
        d.status = "needs_evidence_review"
    elif validation["status"] != "failed" and d.status == "needs_evidence_review":
        d.status = "draft"
    db.commit()
    sync_publishing_item(db, d)
    db.commit()


@router.get("/projects/{project_id}/deliverables", response_model=list[DeliverableOut])
def list_deliverables(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DeliverableOut]:
    project = get_project_or_404(db, project_id)
    order = {"carousel": 0, "static": 1, "reel": 2, "deck": 3}
    ds = sorted(project.deliverables, key=lambda d: order.get(d.format, 9))
    return [deliverable_out(d) for d in ds]


@router.post("/projects/{project_id}/generate", response_model=PipelineRunOut, status_code=202)
def generate_content(
    project_id: str,
    body: GenerateBody | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PipelineRunOut:
    project = get_project_or_404(db, project_id)
    allowed = {"carousel", "static", "reel", "deck"}
    formats = (body.formats if body else None) or ["carousel", "static", "reel"]
    bad = [f for f in formats if f not in allowed]
    if bad:
        raise bad_request(f"Unknown formats: {bad} (allowed: {sorted(allowed)})")
    if project.summary_status != "ready":
        raise bad_request("Run the research pipeline first — content generation needs a research summary.")
    try:
        run = create_run(db, project, "generation")
    except RuntimeError as exc:
        raise bad_request(str(exc)) from exc
    run.meta = {**(run.meta or {}), "formats": formats}
    db.commit()
    start_run_async(run.id)
    db.refresh(run)
    return pipeline_run_out(run)


@router.get("/deliverables/{deliverable_id}", response_model=DeliverableDetailOut)
def get_deliverable(
    deliverable_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DeliverableDetailOut:
    d = _get_deliverable(db, deliverable_id)
    return deliverable_detail_out(d, _blocked_claims(d))


@router.post("/deliverables/{deliverable_id}/edit", response_model=DeliverableDetailOut)
def edit_deliverable(
    deliverable_id: str,
    body: EditVersionIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DeliverableDetailOut:
    d = _get_deliverable(db, deliverable_id)
    if d.status == "published":
        raise conflict("Published content cannot be edited without withdrawing it first.")
    version = d.current_version
    if version is None:
        raise bad_request("There is no content version to edit. Generate content first.")
    # structural validation of the edited payload against the schema
    from app.schemas.content import payload_model_for

    try:
        payload_model_for(d.format).model_validate(body.payload)
    except Exception as exc:
        raise bad_request(f"Edited content failed schema validation: {exc}") from exc

    version, invalidated, message = apply_edit(db, d, version, body.payload, note=body.note, editor=user)
    db.commit()
    _revalidate(db, d)
    d = _get_deliverable(db, deliverable_id)
    return deliverable_detail_out(d, _blocked_claims(d))


@router.post("/deliverables/{deliverable_id}/regenerate-section", response_model=DeliverableDetailOut)
def regenerate_one_section(
    deliverable_id: str,
    target: str,
    index: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DeliverableDetailOut:
    d = _get_deliverable(db, deliverable_id)
    version = d.current_version
    if version is None:
        raise bad_request("Generate content first.")
    if target not in {"caption", "slide", "scene", "headline"}:
        raise bad_request("target must be one of: caption, slide, scene, headline")
    try:
        payload, meta = regenerate_section(
            d.project, d.format, sorted(d.project.claims, key=lambda c: c.id),
            version.payload, target=target, target_index=index,
        )
    except GenerationFallbackError as exc:
        raise bad_request(str(exc)) from exc

    payload["_generation"] = {**(payload.get("_generation") or {}), **meta, "last_regenerated": target}
    version, invalidated, _ = apply_edit(db, d, version, payload, note=f"regenerated {target}", editor=user)
    db.commit()
    _revalidate(db, d)
    d = _get_deliverable(db, deliverable_id)
    return deliverable_detail_out(d, _blocked_claims(d))


@router.post("/deliverables/{deliverable_id}/regenerate-all", response_model=DeliverableDetailOut)
def regenerate_all(
    deliverable_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DeliverableDetailOut:
    d = _get_deliverable(db, deliverable_id)
    if d.status == "awaiting_review":
        raise conflict("This deliverable is awaiting doctor review; withdraw the review or edit instead.")
    if not d.project.summary:
        raise bad_request("Research summary missing — run the pipeline first.")
    fmt = d.format
    claims = sorted(d.project.claims, key=lambda c: c.id)
    try:
        payload, meta = generate_deliverable(d.project, fmt, claims)
    except GenerationFallbackError as exc:
        raise bad_request(str(exc)) from exc
    payload["_generation"] = meta

    old = d.current_version
    had_approval = d.approved_version_id is not None
    new_version = ContentVersion(
        id=new_id("cv"),
        deliverable_id=d.id,
        version_number=(max((v.version_number for v in d.versions), default=0) + 1),
        payload=payload,
        generation_mode=meta.get("mode", "deterministic"),
        generation_mode_label=meta.get("mode_label", ""),
        model_name=meta.get("model_name"),
        prompt_version=meta.get("prompt_version"),
        material_hash=material_hash(payload),
        validation={},
        validation_status="pending",
    )
    db.add(new_version)
    db.flush()
    db.expire(d, ["versions"])
    d.current_version_id = new_version.id
    if had_approval:
        d.approved_version_id = None
        d.status = "awaiting_review"
        add_comment_system(db, d, new_version,
            "Content regenerated after approval. Approval invalidated; the new version awaits doctor review.")
    elif d.status in {"approved", "ready_to_publish", "published"}:
        d.approved_version_id = None
        d.status = "draft"
    elif d.status not in {"awaiting_review"}:
        d.status = "draft"
    db.commit()
    _revalidate(db, d)
    d = _get_deliverable(db, deliverable_id)
    return deliverable_detail_out(d, _blocked_claims(d))


def add_comment_system(db: Session, d: ContentDeliverable, version: ContentVersion, body: str) -> None:
    from app.models import ReviewComment

    db.add(ReviewComment(
        id=new_id("cmt"), deliverable_id=d.id, version_id=version.id,
        reviewer_name="system", body=body, anchor="system",
    ))


@router.post("/deliverables/{deliverable_id}/validate", response_model=DeliverableDetailOut)
def validate_now(
    deliverable_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DeliverableDetailOut:
    d = _get_deliverable(db, deliverable_id)
    if d.current_version is None:
        raise bad_request("No content version to validate.")
    _revalidate(db, d)
    d = _get_deliverable(db, deliverable_id)
    return deliverable_detail_out(d, _blocked_claims(d))


@router.post("/deliverables/{deliverable_id}/submit", response_model=DeliverableDetailOut)
def submit(
    deliverable_id: str,
    body: SubmitForReviewIn | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DeliverableDetailOut:
    d = _get_deliverable(db, deliverable_id)
    submit_for_review(db, d)
    if body and body.note:
        add_comment(db, d, user, f"Submitted for review: {body.note}")
    db.commit()
    d = _get_deliverable(db, deliverable_id)
    return deliverable_detail_out(d, _blocked_claims(d))


@router.post("/deliverables/{deliverable_id}/retract", response_model=DeliverableDetailOut)
def retract(
    deliverable_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DeliverableDetailOut:
    """Move an awaiting-review deliverable back to draft (editor action)."""
    d = _get_deliverable(db, deliverable_id)
    if d.status != "awaiting_review":
        raise conflict("Only deliverables awaiting review can be retracted.")
    d.status = "draft"
    db.commit()
    d = _get_deliverable(db, deliverable_id)
    return deliverable_detail_out(d, _blocked_claims(d))


@router.post("/deliverables/{deliverable_id}/export")
def export_deliverable(
    deliverable_id: str,
    body: ExportIn | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Package the CURRENT version: assets + caption + evidence manifest + approval metadata.

    `kind` selects the export artifact:
      - full             → zip bundle (default, all of the below)
      - evidence_report  → human-readable markdown evidence report
      - source_manifest  → machine-readable JSON of sources + claims + evidence
      - captions         → plain-text caption / voiceover script
    """
    d = _get_deliverable(db, deliverable_id)
    version = d.current_version
    if version is None:
        raise bad_request("No content version to export.")
    kind = (body.kind if body else None) or "full"
    if kind not in EXPORT_KINDS:
        raise bad_request(f"Unknown export kind: {kind} (allowed: {sorted(EXPORT_KINDS)})")

    out_dir = settings.generated_path / version.id
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    review = next(
        (r for r in sorted(d.reviews, key=lambda r: r.id) if r.version_id == version.id and r.decision == "approved"),
        None,
    )
    claims_used = sorted({
        cid
        for cid in (version.validation or {}).get("used_claim_ids", [])
    })
    claims_by_id = {c.id: c for c in d.project.claims}
    manifest = []
    for cid in claims_used:
        c = claims_by_id.get(cid)
        if not c:
            manifest.append({"claim_id": cid, "error": "claim id not found"})
            continue
        manifest.append({
            "claim_id": c.id,
            "claim_text": c.claim_text,
            "status": c.status,
            "risk_level": c.risk_level,
            "study_design": c.study_design,
            "population": c.population,
            "limitations": c.limitations,
            "verification_notes": c.verification_notes,
            "evidence": [
                {
                    "relation": ev.relation,
                    "excerpt": ev.excerpt,
                    "page": ev.page,
                    "section": ev.section,
                    "doi": ev.doi,
                    "url": ev.url,
                    "source_id": ev.source_id,
                    "source_title": ev.source.title if ev.source else None,
                    "source_year": ev.source.year if ev.source else None,
                }
                for ev in c.evidence
            ],
        })

    approval_meta = {
        "deliverable_id": d.id,
        "format": d.format,
        "version": version.version_number,
        "version_id": version.id,
        "material_hash": version.material_hash,
        "generation_mode": version.generation_mode,
        "generation_mode_label": version.generation_mode_label,
        "validation_status": version.validation_status,
        "approved": bool(d.approved_version_id == version.id),
        "approved_by": review.reviewer_name if review else None,
        "approved_at": review.created_at.isoformat() if review and review.created_at else None,
        "approval_comments": review.comments if review else None,
        "current_status": d.status,
    }

    payload = version.payload or {}

    if kind == "evidence_report":
        report_md = _evidence_report_markdown(d, version, payload, manifest, approval_meta)
        path = out_dir / f"evidence_report_{d.format}_v{version.version_number}_{stamp}.md"
        path.write_text(report_md, encoding="utf-8")
        spec = {
            "kind": "export_evidence_report",
            "path": str(path),
            "filename": path.name,
            "mime": "text/markdown",
            "label": f"Evidence report (v{version.version_number})",
        }
    elif kind == "source_manifest":
        manifest_json = {
            "project_id": d.project_id,
            "deliverable_id": d.id,
            "format": d.format,
            "version_id": version.id,
            "version_number": version.version_number,
            "sources": [
                {
                    "id": s.id,
                    "title": s.title,
                    "doi": s.doi,
                    "url": s.canonical_url or s.url,
                    "year": s.year,
                    "journal": s.journal,
                    "authors": s.authors,
                }
                for s in d.project.sources
            ],
            "claims": manifest,
        }
        path = out_dir / f"source_manifest_{d.format}_v{version.version_number}_{stamp}.json"
        path.write_text(json.dumps(manifest_json, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        spec = {
            "kind": "export_source_manifest",
            "path": str(path),
            "filename": path.name,
            "mime": "application/json",
            "label": f"Source manifest (v{version.version_number})",
        }
    elif kind == "captions":
        path = out_dir / f"captions_{d.format}_v{version.version_number}_{stamp}.txt"
        path.write_text(_captions_text(d.format, payload), encoding="utf-8")
        spec = {
            "kind": "export_captions",
            "path": str(path),
            "filename": path.name,
            "mime": "text/plain",
            "label": f"Captions / script (v{version.version_number})",
        }
    else:  # full bundle
        zip_path = out_dir / f"export_{d.format}_v{version.version_number}_{stamp}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for asset in version.assets:
                p = Path(asset.file_path)
                if p.exists():
                    zf.write(p, f"assets/{asset.filename}")
            zf.writestr("content.json", json.dumps(payload, indent=2, ensure_ascii=False, default=str))
            zf.writestr("caption.txt", payload.get("caption", ""))
            zf.writestr("evidence_report.md", _evidence_report_markdown(d, version, payload, manifest, approval_meta))
            zf.writestr("source_manifest.json", json.dumps(
                {"sources": [
                    {"id": s.id, "title": s.title, "doi": s.doi, "url": s.canonical_url or s.url,
                     "year": s.year, "journal": s.journal, "authors": s.authors}
                    for s in d.project.sources
                ], "claims": manifest},
                indent=2, ensure_ascii=False, default=str,
            ))
            zf.writestr("captions.txt", _captions_text(d.format, payload))
            zf.writestr("evidence_manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False, default=str))
            zf.writestr("approval_metadata.json", json.dumps(approval_meta, indent=2, ensure_ascii=False, default=str))
            zf.writestr(
                "README.txt",
                "Steer Research Studio export\n"
                f"Format: {d.format} | version v{version.version_number}\n"
                f"Approved: {approval_meta['approved']} | validation: {version.validation_status}\n"
                f"Generated by: {version.generation_mode_label}\n\n"
                "Contents: content.json, caption.txt, evidence_report.md, source_manifest.json,\n"
                "captions.txt, evidence_manifest.json, approval_metadata.json, assets/.\n\n"
                "Publishing is a manual step: upload the assets and paste the caption yourself.\n"
                "Do not publish content that is not approved for its current version.\n",
            )
        spec = {
            "kind": "export_bundle",
            "path": str(zip_path),
            "filename": zip_path.name,
            "mime": "application/zip",
            "label": f"Full export bundle (v{version.version_number})",
        }

    _register_asset(db, version, spec)
    asset = next(a for a in version.assets if a.file_path == spec["path"])
    return {
        "asset_id": asset.id,
        "filename": asset.filename,
        "download_url": f"/api/assets/{asset.id}",
        "approved": approval_meta["approved"],
        "validation_status": version.validation_status,
        "kind": kind,
    }


def _captions_text(fmt: str, payload: dict) -> str:
    """Plain-text caption / script for the given payload."""
    lines: list[str] = []
    caption = (payload.get("caption") or "").strip()
    if caption:
        lines.append("CAPTION")
        lines.append(caption)
        lines.append("")
    if fmt == "reel":
        lines.append("VOICEOVER / ON-SCREEN SCRIPT")
        hook = (payload.get("hook") or "").strip()
        if hook:
            lines.append(f"Hook: {hook}")
        for sc in payload.get("scenes", []):
            lines.append(
                f"[{sc.get('start_seconds')}s–{sc.get('end_seconds')}s] "
                f"{sc.get('on_screen_text', '')} — {sc.get('voiceover', '')}"
            )
        closing = (payload.get("closing_takeaway") or "").strip()
        if closing:
            lines.append(f"Closing: {closing}")
        lines.append("")
    if fmt == "deck":
        lines.append("DECK TITLES")
        lines.append((payload.get("deck_title") or "").strip())
        sub = (payload.get("subtitle") or "").strip()
        if sub:
            lines.append(sub)
        lines.append("")
        for s in payload.get("slides", []):
            lines.append(f"Slide {s.get('index', 0) + 1}: {s.get('title', '')}")
    hashtags = payload.get("hashtags") or []
    if hashtags:
        lines.append("")
        lines.append("HASHTAGS")
        lines.append(" ".join(hashtags))
    notes = payload.get("source_notes") or []
    if notes:
        lines.append("")
        lines.append("SOURCES")
        for n in notes:
            text = n.get("text", "") if isinstance(n, dict) else str(n)
            doi = n.get("doi") if isinstance(n, dict) else None
            lines.append(f"- {text}" + (f" (doi:{doi})" if doi else ""))
    limitations = payload.get("limitations") or []
    if limitations:
        lines.append("")
        lines.append("LIMITATIONS")
        for l in limitations:
            lines.append(f"- {l}")
    disclaimer = (payload.get("disclaimer") or "").strip()
    if disclaimer:
        lines.append("")
        lines.append("DISCLAIMER")
        lines.append(disclaimer)
    return "\n".join(lines)


def _evidence_report_markdown(d, version, payload, manifest, approval_meta) -> str:
    """Human-readable markdown evidence report for the version."""
    lines = [
        f"# Evidence report — {d.format} v{version.version_number}",
        "",
        f"- Project: `{d.project_id}`",
        f"- Deliverable: `{d.id}`",
        f"- Generation: {version.generation_mode_label}",
        f"- Validation: **{version.validation_status}**",
        f"- Approved: **{approval_meta['approved']}**"
        + (f" by {approval_meta['approved_by']}" if approval_meta.get("approved_by") else ""),
        "",
        "> Deterministic rule-based checks; not a clinical fact-check. Doctor review still required.",
        "",
    ]

    used = (version.validation or {}).get("used_claim_ids", [])
    lines.append(f"## Claims used ({len(used)})")
    lines.append("")
    by_id = {m.get("claim_id"): m for m in manifest}
    for cid in used:
        m = by_id.get(cid)
        lines.append(f"### {cid}")
        if not m or m.get("error"):
            lines.append("- **Claim id not found in registry.**")
            lines.append("")
            continue
        lines.append(f"- Text: {m.get('claim_text', '')}")
        lines.append(f"- Status: `{m.get('status')}` · Risk: `{m.get('risk_level')}`")
        if m.get("study_design"):
            lines.append(f"- Study design: {m['study_design']}")
        if m.get("population"):
            lines.append(f"- Population: {m['population']}")
        if m.get("limitations"):
            lines.append(f"- Limitations: {m['limitations']}")
        evs = m.get("evidence") or []
        if evs:
            lines.append("- Evidence passages:")
            for ev in evs:
                src = ev.get("source_title") or ev.get("source_id") or "source"
                page = f" p.{ev['page']}" if ev.get("page") else ""
                lines.append(
                    f"  - [{ev.get('relation')}] {src}{page}: “{ev.get('excerpt', '')[:300]}”"
                )
        else:
            lines.append("- **No persisted evidence passages.**")
        lines.append("")

    issues = (version.validation or {}).get("issues") or []
    lines.append(f"## Validation issues ({len(issues)})")
    lines.append("")
    if not issues:
        lines.append("No issues recorded.")
    for i in issues:
        lines.append(f"- **{i.get('severity', '?')}** `{i.get('rule')}`"
                     + (f" ({i.get('claim_id')})" if i.get("claim_id") else "")
                     + f": {i.get('message')}")
    lines.append("")
    limitations = payload.get("limitations") or []
    if limitations:
        lines.append("## Limitations")
        for l in limitations:
            lines.append(f"- {l}")
        lines.append("")
    disclaimer = (payload.get("disclaimer") or "").strip()
    if disclaimer:
        lines.append("## Disclaimer")
        lines.append(disclaimer)
        lines.append("")
    return "\n".join(lines)


def _register_asset(db: Session, version: ContentVersion, spec: dict) -> None:
    existing = next((a for a in version.assets if a.file_path == spec["path"]), None)
    if existing:
        return
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
    db.commit()
    db.expire(version, ["assets"])
