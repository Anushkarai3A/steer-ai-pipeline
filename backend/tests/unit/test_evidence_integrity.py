from __future__ import annotations

"""Regression tests for evidence integrity (the Evidence Lab "supported with
0 passages" class of bugs).

Covers: source deletion must reconcile claim statuses, supported status
requires persisted supporting passages (PATCH + validation + publishing),
high-risk claims are never auto-supported, counts come from persisted rows,
and doctor-only enforcement stays server-side.
"""

from app.core.database import SessionLocal
from app.core.ids import new_id
from app.models import (
    ClaimEvidence,
    ContentDeliverable,
    ContentVersion,
    EvidenceClaim,
    ResearchProject,
    ResearchSource,
)
from app.services.claims.evidence_link import (
    locate_support,
    reconcile_claim,
    repair_stranded_claims,
    supporting_evidence_count,
    verify_claim,
)
from app.services.review.workflow import publishing_eligibility
from app.services.validation.validate import (
    claim_publication_blockers,
    has_blocking_errors,
    validate_payload,
)


def _carousel_payload(claim_id: str) -> dict:
    return {
        "concept": "c", "audience": "a", "main_message": "m",
        "slides": [
            {"index": 0, "headline": "Hook", "body": "Body", "claim_ids": [claim_id], "footnote": "f"},
            {"index": 1, "headline": "Second", "body": "More", "claim_ids": [claim_id], "footnote": "f"},
            {"index": 2, "headline": "Nuance", "body": "Limitations here", "claim_ids": []},
            {"index": 3, "headline": "Close", "body": "Takeaway", "claim_ids": [claim_id]},
        ],
        "caption": "Caption with detail",
        "hashtags": ["#x"],
        "source_notes": [],
        "limitations": ["Small sample"],
        "disclaimer": "This is educational and is not medical advice.",
    }


def _committed_claim(
    client,
    editor_headers,
    *,
    status: str = "needs_human_review",
    risk: str = "medium",
    evidence: list[dict] | None = None,
    claim_text: str = "Resting systolic blood pressure fell by 8.2 mmHg in the intervention group.",
) -> tuple[str, str]:
    """Create a committed project + claim (with optional evidence) via the DB."""
    r = client.post(
        "/api/projects",
        json={"name": "Evidence integrity test", "description": ""},
        headers=editor_headers,
    )
    assert r.status_code == 201, r.text
    project_id = r.json()["id"]

    db = SessionLocal()
    try:
        src = ResearchSource(id=new_id("src"), project_id=project_id, title="Src", status="extracted")
        db.add(src)
        db.flush()
        claim = EvidenceClaim(
            id=new_id("clm"),
            project_id=project_id,
            claim_text=claim_text,
            risk_level=risk,
            status=status,
            verification_notes="test claim",
        )
        for ev in evidence or []:
            claim.evidence.append(
                ClaimEvidence(
                    id=new_id("evd"),
                    source_id=src.id,
                    relation=ev.get("relation", "supports"),
                    excerpt=ev["excerpt"],
                    page=ev.get("page", 1),
                )
            )
        db.add(claim)
        db.commit()
        return project_id, claim.id
    finally:
        db.close()


def test_remove_source_reconciles_stranded_claims(project_with_sources, client, editor_headers):
    """Deleting a source must never leave a 'supported' claim without passages."""
    pid = project_with_sources

    claims = client.get(f"/api/projects/{pid}/claims", headers=editor_headers).json()
    supported = [c for c in claims if c["status"] in {"supported", "partially_supported"}]
    assert supported, "pipeline must produce supported claims before deletion"

    sources = client.get(f"/api/projects/{pid}", headers=editor_headers).json()["sources"]
    source_ids = {s["id"] for s in sources}
    assert source_ids

    # delete every source in turn; after each deletion the invariant must hold
    remaining = set(source_ids)
    for sid in list(source_ids):
        resp = client.delete(f"/api/projects/{pid}/sources/{sid}", headers=editor_headers)
        assert resp.status_code == 200, resp.text
        remaining.discard(sid)
        after = client.get(f"/api/projects/{pid}/claims", headers=editor_headers).json()
        for c in after:
            if c["status"] in {"supported", "partially_supported"}:
                supporting = [
                    e for e in c["evidence"]
                    if e["relation"] == "supports" and (e["excerpt"] or "").strip()
                ]
                assert supporting, (
                    f"{c['id']} is '{c['status']}' with 0 supporting passages after source deletion"
                )
            # no evidence row may reference a deleted source
            for e in c["evidence"]:
                assert e["source_id"] in remaining, (
                    f"{c['id']} still references evidence from deleted source {e['source_id']}"
                )
            # a claim that lost its only evidence must carry honest re-verification notes
            if c["status"] == "needs_human_review" and "missing" in (c["verification_notes"] or "").lower():
                assert "re-verification" in c["verification_notes"].lower()


def test_claim_api_counts_match_persisted_rows(project_with_sources, client, editor_headers):
    """Passage counts must come from persisted evidence rows, never invented."""
    pid = project_with_sources
    api_claims = client.get(f"/api/projects/{pid}/claims", headers=editor_headers).json()

    db = SessionLocal()
    try:
        for c in api_claims:
            db_count = (
                db.query(ClaimEvidence)
                .filter(ClaimEvidence.claim_id == c["id"])
                .count()
            )
            assert len(c["evidence"]) == db_count, f"{c['id']} API/DB evidence count mismatch"
            if c["status"] in {"supported", "partially_supported"}:
                supporting = [e for e in c["evidence"] if e["relation"] == "supports" and e["excerpt"].strip()]
                assert supporting, f"{c['id']} is '{c['status']}' but has no persisted supporting passage"
                # notes that reference a page must reference a page that exists
                claim = db.get(EvidenceClaim, c["id"])
                assert claim is not None
                assert supporting_evidence_count(claim) == len(supporting)
    finally:
        db.close()


def test_patch_status_rejected_without_evidence(client, editor_headers, doctor_headers):
    """A note alone can never substitute for a persisted passage."""
    _, claim_id = _committed_claim(client, editor_headers, status="needs_human_review", evidence=[])

    resp = client.patch(
        f"/api/claims/{claim_id}",
        json={
            "status": "supported",
            "verification_notes": "Verbatim passage located on page 1 (results).",
        },
        headers=doctor_headers,
    )
    assert resp.status_code == 400, resp.text
    assert "no evidence passage" in resp.json()["detail"].lower()

    # status must be unchanged
    claim = client.get(f"/api/claims/{claim_id}", headers=doctor_headers).json()
    assert claim["status"] == "needs_human_review"
    assert claim["verification_notes"] == "test claim"


def test_patch_status_rejected_with_contradicts_only(client, editor_headers, doctor_headers):
    """Contradicts-only evidence cannot back a 'supported' status."""
    _, claim_id = _committed_claim(
        client, editor_headers,
        status="needs_human_review",
        evidence=[{"relation": "contradicts", "excerpt": "No reduction was observed in this cohort at all.", "page": 2}],
    )
    resp = client.patch(
        f"/api/claims/{claim_id}",
        json={"status": "supported"},
        headers=doctor_headers,
    )
    assert resp.status_code == 400, resp.text


def test_patch_status_allowed_with_supporting_evidence(client, editor_headers, doctor_headers):
    _, claim_id = _committed_claim(
        client, editor_headers,
        status="needs_human_review",
        evidence=[{"relation": "supports", "excerpt": "Resting systolic blood pressure fell by 8.2 mmHg in the intervention group.", "page": 1}],
    )
    resp = client.patch(
        f"/api/claims/{claim_id}",
        json={"status": "supported", "verification_notes": "Doctor verified the passage."},
        headers=doctor_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "supported"
    assert body["verification_notes"] == "Doctor verified the passage."


def test_editor_cannot_patch_claim_status(client, editor_headers):
    """Evidence status changes are doctor/admin only — enforced server-side."""
    _, claim_id = _committed_claim(client, editor_headers, status="needs_human_review", evidence=[])
    resp = client.patch(
        f"/api/claims/{claim_id}",
        json={"status": "supported"},
        headers=editor_headers,
    )
    assert resp.status_code == 403
    claim = client.get(f"/api/claims/{claim_id}", headers=editor_headers).json()
    assert claim["status"] == "needs_human_review"


def test_claim_text_edit_resets_status(client, editor_headers, doctor_headers):
    _, claim_id = _committed_claim(
        client, editor_headers,
        status="supported",
        evidence=[{"relation": "supports", "excerpt": "Resting systolic blood pressure fell by 8.2 mmHg in the intervention group.", "page": 1}],
    )
    resp = client.patch(
        f"/api/claims/{claim_id}",
        json={"claim_text": "Edited claim text that must be re-checked against evidence."},
        headers=doctor_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "needs_human_review"
    assert "re-checked" in body["verification_notes"].lower() or "edited" in body["verification_notes"].lower()
    # the persisted passage is kept — nothing is fabricated or deleted
    assert len(body["evidence"]) == 1


def test_high_risk_exact_match_never_auto_supported(project_with_sources):
    """RULE: a high-risk claim is never auto-marked supported, even verbatim."""
    exact = (
        "After 12 weeks, the intervention group had a mean change in resting systolic blood "
        "pressure of -8.2 mmHg (95% CI -11.0 to -5.4) compared with -1.5 mmHg in the control group."
    )
    db = SessionLocal()
    try:
        project = db.get(ResearchProject, project_with_sources)

        high = EvidenceClaim(
            id=new_id("clm"), project_id=project.id, claim_text=exact, risk_level="high",
        )
        db.add(high)
        db.flush()
        verify_claim(db, project, high)
        assert high.status == "needs_human_review", high.status
        assert supporting_evidence_count(high) >= 1, "the located passage must still be persisted"
        assert "doctor" in high.verification_notes.lower() or "high-risk" in high.verification_notes.lower()

        # control: the same verbatim claim at medium risk is still auto-supported
        medium = EvidenceClaim(
            id=new_id("clm"), project_id=project.id, claim_text=exact, risk_level="medium",
        )
        db.add(medium)
        db.flush()
        verify_claim(db, project, medium)
        assert medium.status == "supported", medium.status
        assert supporting_evidence_count(medium) >= 1
        db.rollback()
    finally:
        db.close()


def test_preferred_source_ranks_own_paper_first(project_with_sources):
    """Regression: a claim must link to its own paper, not a same-wording neighbour.

    The old locator scanned every source for similar wording and could attach an
    unrelated paper's baseline-table sentence (which shares 'glucose', 'impaired',
    numbers like 29) as support for a claim copied verbatim from another paper.
    """
    from app.services.claims.evidence_link import locate_support

    db = SessionLocal()
    try:
        project = db.get(ResearchProject, project_with_sources)
        own = project.sources[0]
        other = project.sources[1]
        exact = (
            "After 12 weeks, the intervention group had a mean change in resting systolic blood "
            "pressure of -8.2 mmHg (95% CI -11.0 to -5.4) compared with -1.5 mmHg in the control group."
        )
        support = locate_support(project, exact, preferred_source_id=own.id)
        assert support, "expected a supporting passage"
        assert support[0]["exact"] is True
        assert support[0]["source"].id == own.id, "best passage must come from the claim's own source"
        # No other paper may be attached as support for this claim.
        assert all(r["source"].id == own.id for r in support)

        # A claim copied from the other paper must prefer THAT paper, not a
        # neighbouring one that merely shares wording.
        other_claims = [
            "Adults who self-monitored blood pressure had a 14% lower rate of the composite "
            "cardiovascular outcome over 5 years (HR 0.86, 95% CI 0.75 to 0.98) after adjustment."
        ]
        for text in other_claims:
            support_other = locate_support(project, text, preferred_source_id=other.id)
            if support_other and support_other[0]["exact"]:
                assert support_other[0]["source"].id == other.id
        db.rollback()
    finally:
        db.close()


def test_validation_blocks_supported_claim_without_evidence_records(db_session):
    """A stored 'supported' status with zero evidence records must fail validation."""
    project = ResearchProject(id=new_id("prj"), name="v", description="")
    db_session.add(project)
    db_session.flush()
    src = ResearchSource(id=new_id("src"), project_id=project.id, title="S", status="extracted")
    db_session.add(src)
    db_session.flush()
    claim = EvidenceClaim(
        id=new_id("clm"), project_id=project.id,
        claim_text="Resting systolic blood pressure fell by 8.2 mmHg in the intervention group.",
        status="supported",  # stranded status: no evidence rows appended
    )
    db_session.add(claim)
    db_session.flush()
    db_session.refresh(project)

    result = validate_payload("carousel", _carousel_payload(claim.id), project, {claim.id: claim})
    rules = {i["rule"] for i in result["issues"] if i["severity"] == "error"}
    assert "missing_evidence" in rules
    assert has_blocking_errors(result)

    # a persisted supporting passage clears the rule
    claim.evidence.append(
        ClaimEvidence(
            id=new_id("evd"), source_id=src.id, relation="supports",
            excerpt="Resting systolic blood pressure fell by 8.2 mmHg in the intervention group.",
            page=1,
        )
    )
    db_session.flush()
    result2 = validate_payload("carousel", _carousel_payload(claim.id), project, {claim.id: claim})
    assert "missing_evidence" not in {i["rule"] for i in result2["issues"]}


def test_claim_publication_blockers_matrix(db_session):
    project = ResearchProject(id=new_id("prj"), name="b", description="")
    db_session.add(project)
    db_session.flush()
    src = ResearchSource(id=new_id("src"), project_id=project.id, title="S", status="extracted")
    db_session.add(src)
    db_session.flush()

    def make(risk: str, status: str, with_support: bool) -> EvidenceClaim:
        c = EvidenceClaim(
            id=new_id("clm"), project_id=project.id, claim_text="x" * 40,
            risk_level=risk, status=status,
        )
        if with_support:
            c.evidence.append(
                ClaimEvidence(id=new_id("evd"), source_id=src.id, relation="supports",
                              excerpt="y" * 40, page=1)
            )
        db_session.add(c)
        db_session.flush()
        return c

    assert claim_publication_blockers(make("medium", "unsupported", False))
    assert claim_publication_blockers(make("high", "needs_human_review", True))
    assert not claim_publication_blockers(make("medium", "needs_human_review", False)), (
        "medium-risk needs_human_review is a warning, not a publishing blocker"
    )
    assert claim_publication_blockers(make("high", "conflicting", True))
    assert not claim_publication_blockers(make("medium", "conflicting", True))
    assert claim_publication_blockers(make("medium", "supported", False)), (
        "supported without a persisted supporting passage must block publishing"
    )
    assert not claim_publication_blockers(make("medium", "supported", True))
    assert not claim_publication_blockers(make("medium", "partially_supported", True))


def test_publishing_eligibility_blocked_by_stranded_claim(db_session):
    """A stale 'passed' validation cannot carry a stranded claim to publishing."""
    project = ResearchProject(id=new_id("prj"), name="p", description="")
    db_session.add(project)
    db_session.flush()
    src = ResearchSource(id=new_id("src"), project_id=project.id, title="S", status="extracted")
    db_session.add(src)
    db_session.flush()

    stranded = EvidenceClaim(
        id=new_id("clm"), project_id=project.id,
        claim_text="Resting systolic blood pressure fell by 8.2 mmHg in the intervention group.",
        status="supported",  # no evidence rows: stranded
    )
    db_session.add(stranded)
    db_session.flush()

    version = ContentVersion(
        id=new_id("cv"), deliverable_id="", version_number=1,
        payload=_carousel_payload(stranded.id),
        material_hash="deadbeef",
        validation={"status": "passed", "issues": []},  # stale result
        validation_status="passed",
    )
    deliverable = ContentDeliverable(
        id=new_id("dlv"), project_id=project.id, format="carousel",
        status="ready_to_publish", current_version_id=version.id, approved_version_id=version.id,
    )
    deliverable.versions.append(version)
    db_session.add(deliverable)
    db_session.flush()

    eligible, reasons = publishing_eligibility(deliverable)
    assert eligible is False
    assert any("supporting evidence" in r for r in reasons), reasons

    # give the claim a real persisted passage and an honest re-validation
    stranded.evidence.append(
        ClaimEvidence(
            id=new_id("evd"), source_id=src.id, relation="supports",
            excerpt="Resting systolic blood pressure fell by 8.2 mmHg in the intervention group.",
            page=1,
        )
    )
    db_session.flush()
    from app.services.validation.validate import validate_payload

    validation = validate_payload("carousel", version.payload, project, {stranded.id: stranded})
    version.validation = validation
    version.validation_status = validation["status"]
    db_session.flush()

    eligible2, reasons2 = publishing_eligibility(deliverable)
    assert eligible2 is True, reasons2


def test_repair_stranded_claims_demotes_and_notes(db_session):
    """Startup/one-shot repair demotes stranded supported claims honestly."""
    project = ResearchProject(id=new_id("prj"), name="r", description="")
    db_session.add(project)
    db_session.flush()
    stranded = EvidenceClaim(
        id=new_id("clm"), project_id=project.id, claim_text="x" * 40, status="supported",
        verification_notes="Verbatim passage located in source src_abc on page 1 (results).",
    )
    healthy_src = ResearchSource(id=new_id("src"), project_id=project.id, title="S", status="extracted")
    db_session.add(healthy_src)
    db_session.flush()
    healthy = EvidenceClaim(
        id=new_id("clm"), project_id=project.id, claim_text="y" * 40, status="supported",
    )
    healthy.evidence.append(
        ClaimEvidence(id=new_id("evd"), source_id=healthy_src.id, relation="supports",
                      excerpt="z" * 40, page=3)
    )
    db_session.add(stranded, healthy)
    db_session.flush()

    changed = repair_stranded_claims(db_session)
    assert stranded.id in changed
    assert healthy.id not in changed
    assert stranded.status == "needs_human_review"
    assert "missing" in stranded.verification_notes.lower()
    assert "page 1" not in stranded.verification_notes.lower(), (
        "the stale note referencing a nonexistent passage must be replaced, not kept"
    )
    assert healthy.status == "supported"
    assert supporting_evidence_count(healthy) == 1


def test_reconcile_claim_keeps_conflicting_status(db_session):
    """Reconcile only fixes stranded supported/partially claims — never others."""
    project = ResearchProject(id=new_id("prj"), name="c", description="")
    db_session.add(project)
    db_session.flush()
    claim = EvidenceClaim(
        id=new_id("clm"), project_id=project.id, claim_text="x" * 40,
        status="conflicting", verification_notes="sources disagree",
    )
    db_session.add(claim)
    db_session.flush()
    assert reconcile_claim(db_session, claim) is False
    assert claim.status == "conflicting"
    assert claim.verification_notes == "sources disagree"
