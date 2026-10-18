from __future__ import annotations

from app.core.database import SessionLocal
from app.models import EvidenceClaim, ResearchProject


def _claim_dicts(project_id: str) -> list[dict]:
    db = SessionLocal()
    try:
        project = db.get(ResearchProject, project_id)
        return [
            {
                "id": c.id,
                "claim_text": c.claim_text,
                "status": c.status,
                "risk_level": c.risk_level,
                "evidence": [
                    {"id": e.id, "source_id": e.source_id, "excerpt": e.excerpt, "page": e.page,
                     "relation": e.relation, "doi": e.doi}
                    for e in c.evidence
                ],
            }
            for c in sorted(project.claims, key=lambda c: c.id)
        ]
    finally:
        db.close()


def test_pipeline_creates_traceable_claims(project_with_sources):
    claims = _claim_dicts(project_with_sources)
    assert len(claims) >= 4, "expected several candidate claims from the sample papers"
    linked = [c for c in claims if c["evidence"]]
    assert linked, "claims must link to evidence records"
    for c in linked:
        assert c["status"] in {"supported", "partially_supported", "conflicting", "needs_human_review"}
        for ev in c["evidence"]:
            assert ev["excerpt"] and len(ev["excerpt"]) > 20, "excerpt must be real text"
            assert ev["page"] is None or ev["page"] >= 1
            assert ev["source_id"], "evidence must reference a stored source"


def test_evidence_excerpt_comes_from_source_text(project_with_sources):
    db = SessionLocal()
    try:
        project = db.get(ResearchProject, project_with_sources)
        claim = next(c for c in project.claims if c.evidence)
        ev = claim.evidence[0]
        source = ev.source
        assert source is not None
        page = next(p for p in source.document.pages if p["page"] == ev.page)
        from app.core.text import normalize

        assert normalize(ev.excerpt) in normalize(page["text"]), (
            "evidence excerpt must appear verbatim in the stored source page"
        )
    finally:
        db.close()


def test_claim_without_passage_is_not_marked_supported(project_with_sources):
    """RULE 1: a claim with no traceable evidence must never pass as supported."""
    from app.services.claims.evidence_link import locate_support

    db = SessionLocal()
    try:
        project = db.get(ResearchProject, project_with_sources)
        results = locate_support(project, "Quantum teleportation cures morning fatigue in astronauts by 400%.")
        assert results == [] or results[0]["score"] < 0.9
        claim = EvidenceClaim(
            id="CLM-TEST",
            project_id=project.id,
            claim_text="Quantum teleportation cures morning fatigue in astronauts by 400%.",
            status="needs_human_review",
        )
        from app.services.claims.evidence_link import verify_claim

        db.add(claim)
        db.flush()
        verify_claim(db, project, claim)
        assert claim.status in {"unsupported", "needs_human_review"}, claim.status
        assert claim.evidence == [] or all(e.relation != "supports" for e in claim.evidence)
        assert "no supporting passage" in claim.verification_notes.lower()
    finally:
        db.close()


def test_conflicting_sources_surface_disagreement(project_with_sources):
    from app.services.claims.evidence_link import locate_contradiction, locate_support

    db = SessionLocal()
    try:
        project = db.get(ResearchProject, project_with_sources)
        # Statement A appears verbatim in paper A (supported); paper B must not
        # be forced into agreement.
        claim_a = (
            "After 12 weeks, the intervention group had a mean change in resting systolic blood "
            "pressure of -8.2 mmHg (95% CI -11.0 to -5.4) compared with -1.5 mmHg in the control group."
        )
        support = locate_support(project, claim_a)
        assert support and support[0]["exact"] is True

        # Now look for a contradiction of a positive-direction claim across sources.
        contradiction = locate_contradiction(
            project,
            "The intervention was associated with a reduction in resting systolic blood pressure.",
            exclude_source_id=support[0]["source"].id,
        )
        # no exact contradiction in these papers — function must not invent one
        assert contradiction is None or contradiction["score"] >= 0.6
    finally:
        db.close()


def test_explicit_contradiction_detected(db_session):
    """Two synthetic sources with opposite statements must surface as conflicting."""
    from app.services.claims.evidence_link import locate_contradiction, verify_claim
    from app.services.sample_project import _render_synthetic_pdf
    from app.services.extraction.pdf_extractor import extract_pdf
    from app.core.ids import new_id
    from app.models import ExtractedDocument, ResearchProject, ResearchSource
    import hashlib, tempfile, os

    project = ResearchProject(id=new_id("prj"), name="conflict", description="")
    db_session.add(project)
    db_session.flush()

    texts = [
        "Results\n\nAfter the program, systolic blood pressure fell by 8.2 mmHg in the intervention group.",
        "Results\n\nIn this second cohort, systolic blood pressure did not fall by 8.2 mmHg after the program in the intervention group.",
    ]
    for i, text in enumerate(texts):
        pdf = _render_synthetic_pdf(f"conflict-{i}", [text])
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf)
            path = f.name
        result = extract_pdf(path)
        os.unlink(path)
        src_id = new_id("src")
        source = ResearchSource(
            id=src_id, project_id=project.id, kind="pdf", file_path=path,
            title=f"Conflict paper {i}", status="extracted",
        )
        db_session.add(source)
        db_session.flush()
        db_session.add(ExtractedDocument(
            id=new_id("doc"), source_id=src_id,
            full_text=result["full_text"], pages=result["pages"], method="pymupdf",
        ))
    db_session.flush()
    db_session.refresh(project)

    claim = EvidenceClaim(
        id="CLM-CFL", project_id=project.id,
        claim_text="After the program, systolic blood pressure fell by 8.2 mmHg in the intervention group.",
    )
    db_session.add(claim)
    db_session.flush()
    verify_claim(db_session, project, claim)
    assert claim.status == "conflicting", claim.status
    relations = {e.relation for e in claim.evidence}
    assert "contradicts" in relations and "supports" in relations
    db_session.rollback()


def test_claim_ids_are_stable_and_sequential(project_with_sources):
    claims = _claim_dicts(project_with_sources)
    ids = [c["id"] for c in claims]
    assert ids == sorted(ids)
    assert all(i.startswith("CLM-") for i in ids)
    assert len(set(ids)) == len(ids)
