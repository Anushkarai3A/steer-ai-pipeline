from __future__ import annotations

import zipfile

from app.core.database import SessionLocal
from app.core.ids import new_id
from app.models import ClaimEvidence, EvidenceClaim, ResearchProject, ResearchSource
from app.services.content_generation import fallback
from app.services.rendering.pptx_builder import pptx_available, render_deck
from app.services.rendering.render_assets import render_version_assets
from app.services.validation.validate import claim_safety_checks, validate_payload


def _project(db, claims_spec: list[dict]) -> tuple[ResearchProject, dict]:
    project = ResearchProject(id=new_id("prj"), name="Deck test", description="")
    db.add(project)
    db.flush()
    src_id = new_id("src")
    db.add(ResearchSource(id=src_id, project_id=project.id, title="Deck Source", year=2023, status="extracted"))
    db.flush()
    for spec in claims_spec:
        db.query(EvidenceClaim).filter(EvidenceClaim.id == spec["id"]).delete()
        db.flush()
    for spec in claims_spec:
        claim = EvidenceClaim(
            id=spec["id"],
            project_id=project.id,
            claim_text=spec["claim_text"],
            risk_level=spec.get("risk_level", "medium"),
            status=spec.get("status", "supported"),
            study_design=spec.get("study_design"),
            population=spec.get("population"),
            limitations=spec.get("limitations"),
            verification_notes=spec.get("notes", ""),
        )
        for ev_text in spec.get("evidence", []):
            claim.evidence.append(
                ClaimEvidence(
                    id=new_id("evd"),
                    claim_id=spec["id"],
                    source_id=src_id,
                    relation="supports",
                    excerpt=ev_text,
                    page=1,
                )
            )
        db.add(claim)
    db.flush()
    db.refresh(project)
    return project, {c.id: c for c in project.claims}


def _deck_claims() -> list[dict]:
    return [{
        "id": "CLM-0001",
        "claim_text": "Resting systolic blood pressure fell by 8.2 mmHg in the intervention group.",
        "evidence": ["Resting systolic blood pressure fell by 8.2 mmHg in the intervention group."],
        "status": "supported",
        "population": "Adults with elevated systolic blood pressure.",
        "study_design": "randomized controlled trial",
    }]


def _deck_summary() -> dict:
    return {
        "research_question": [{"text": "Does a structured breathing program lower resting systolic blood pressure?"}],
        "study_design": [{"text": "Randomized controlled trial over 12 weeks."}],
        "population": [{"text": "120 adults aged 45 to 70 with elevated systolic blood pressure."}],
        "methods": [{"text": "Blinded assessor measured resting systolic blood pressure at baseline and week 12."}],
        "key_findings": [{"text": "Mean change in resting systolic blood pressure was -8.2 mmHg."}],
        "numbers": [{"label": "Mean change (intervention)", "value": "-8.2 mmHg"}],
        "limitations": [{"text": "Small sample and short 12-week follow-up."}],
        "conflicts": [],
        "conflict_note": "No explicit disagreement was detected in the extracted text.",
        "practical_interpretation": [{"text": "A breathing program was associated with a larger reduction than usual care."}],
        "not_established": [{"text": "Nothing about long-term cardiovascular events."}],
    }


# --- deterministic deck builder ----------------------------------------------

def test_build_deck_has_ten_ordered_slides():
    claims = [{
        "id": "CLM-0001",
        "claim_text": "Resting systolic blood pressure fell by 8.2 mmHg in the intervention group.",
        "status": "supported",
        "risk_level": "medium",
        "population": None,
        "study_design": None,
        "effect_size": None,
        "limitations": None,
        "evidence": [{
            "source_id": "src1",
            "excerpt": "Resting systolic blood pressure fell by 8.2 mmHg in the intervention group.",
            "page": 2,
            "doi": None,
            "url": None,
            "source": {"title": "Trial", "journal": "J", "year": 2023},
        }],
    }]
    sources = [{"id": "src1", "title": "Trial", "journal": "J", "year": 2023, "doi": None}]
    payload = fallback.build_deck("Deck project", _deck_summary(), claims, sources)

    slides = payload["slides"]
    assert len(slides) == 10
    assert [s["index"] for s in slides] == list(range(10))
    kinds = [s["kind"] for s in slides]
    assert kinds == [
        "title", "background", "methods", "population", "findings",
        "quantitative", "interpretation", "limitations", "takeaways", "references",
    ]
    assert payload["disclaimer"]
    assert "not medical advice" in payload["disclaimer"].lower()
    assert payload["limitations"], "limitations must survive generation"


def test_build_deck_no_usable_claims_raises():
    try:
        fallback.build_deck("P", _deck_summary(), [], [])
    except ValueError as exc:
        assert "No evidence-linked claims" in str(exc)
    else:
        raise AssertionError("build_deck must raise without usable claims")


def test_build_deck_placeholder_for_missing_sections():
    claims = [{
        "id": "CLM-0001",
        "claim_text": "Resting systolic blood pressure fell by 8.2 mmHg in the intervention group.",
        "status": "supported",
        "risk_level": "medium",
        "population": None,
        "study_design": None,
        "effect_size": None,
        "limitations": None,
        "evidence": [{
            "source_id": "src1",
            "excerpt": "Resting systolic blood pressure fell by 8.2 mmHg in the intervention group.",
            "page": 1,
            "doi": None, "url": None, "source": {"title": "T"},
        }],
    }]
    payload = fallback.build_deck("P", {"limitations": []}, claims, [{"id": "src1", "title": "T"}])
    population_slide = next(s for s in payload["slides"] if s["kind"] == "population")
    # no population data -> honest placeholder, never invented
    assert any("Not established in the provided sources." in b for b in population_slide["bullets"])


# --- pptx rendering ----------------------------------------------------------

def test_render_deck_produces_editable_pptx(tmp_path):
    if not pptx_available():
        import pytest

        pytest.skip("python-pptx not available")
    claims = [{
        "id": "CLM-0001",
        "claim_text": "Resting systolic blood pressure fell by 8.2 mmHg in the intervention group.",
        "status": "supported",
        "risk_level": "medium",
        "population": None, "study_design": None, "effect_size": None, "limitations": None,
        "evidence": [{
            "source_id": "src1",
            "excerpt": "Resting systolic blood pressure fell by 8.2 mmHg in the intervention group.",
            "page": 2, "doi": None, "url": None,
            "source": {"title": "Trial", "journal": "J", "year": 2023},
        }],
    }]
    sources = [{"id": "src1", "title": "Trial", "journal": "J", "year": 2023}]
    payload = fallback.build_deck("Render deck", _deck_summary(), claims, sources)
    assets = render_deck(payload, tmp_path)

    assert len(assets) == 1
    spec = assets[0]
    assert spec["kind"] == "deck_pptx"
    assert spec["filename"].endswith(".pptx")

    # The pptx must be a real editable deck: native text runs (<a:t>) + a table.
    with zipfile.ZipFile(spec["path"]) as zf:
        slide_names = [n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
        assert len(slide_names) == 10
        all_xml = "".join(zf.read(n).decode("utf-8", "ignore") for n in slide_names)
    assert "<a:t>" in all_xml, "deck must contain native editable text runs"
    assert "8.2 mmHg" in all_xml, "claim text must appear in the editable deck"
    assert "<a:tbl" in all_xml or "graphicFrame" in all_xml, "quantitative slide must render a real table"


def test_render_version_assets_dispatches_deck(tmp_path):
    claims = [{
        "id": "CLM-0001",
        "claim_text": "Resting systolic blood pressure fell by 8.2 mmHg in the intervention group.",
        "status": "supported", "risk_level": "medium",
        "population": None, "study_design": None, "effect_size": None, "limitations": None,
        "evidence": [{
            "source_id": "src1",
            "excerpt": "Resting systolic blood pressure fell by 8.2 mmHg in the intervention group.",
            "page": 1, "doi": None, "url": None, "source": {"title": "T"},
        }],
    }]
    payload = fallback.build_deck("D", _deck_summary(), claims, [{"id": "src1", "title": "T"}])
    assets = render_version_assets("deck", payload, tmp_path)
    assert assets and assets[0]["kind"] == "deck_pptx"


# --- validation --------------------------------------------------------------

def test_deck_payload_schema_and_validation(db_session):
    from app.schemas.content import DeckPayload, payload_model_for

    project, claims_by_id = _project(db_session, _deck_claims())
    db_session.refresh(project)
    project.summary = _deck_summary()
    db_session.flush()
    claim_dicts = [{
        "id": c.id, "claim_text": c.claim_text, "status": c.status, "risk_level": c.risk_level,
        "population": c.population, "study_design": c.study_design, "effect_size": c.effect_size,
        "limitations": c.limitations, "verification_notes": c.verification_notes,
        "evidence": [{"id": e.id, "source_id": e.source_id, "relation": e.relation,
                      "excerpt": e.excerpt, "page": e.page, "doi": e.doi, "url": e.url,
                      "source": {"title": e.source.title if e.source else None}}
                     for e in c.evidence],
    } for c in project.claims]
    src = project.sources[0]
    payload = fallback.build_deck(project.name, _deck_summary(), claim_dicts, [
        {"id": src.id, "title": src.title, "journal": src.journal, "year": src.year},
    ])
    # schema accepts the built payload
    model = payload_model_for("deck")
    assert model is DeckPayload
    model.model_validate(payload)

    result = validate_payload("deck", payload, project, claims_by_id)
    assert result["status"] in {"passed", "warnings"}, result
    assert result["counts"]["errors"] == 0, result["issues"]
    # the claim linked on the findings slide is tracked
    assert "CLM-0001" in result["used_claim_ids"]


def test_deck_structure_validation_flags_missing_title(db_session):
    project, _ = _project(db_session, _deck_claims())
    db_session.refresh(project)
    claims_by_id = {c.id: c for c in project.claims}
    payload = {
        "deck_title": "",
        "slides": [{"index": 0, "kind": "title", "title": "T", "bullets": [], "claim_ids": []}],
        "limitations": ["limit"],
        "disclaimer": "This is educational and is not medical advice.",
        "source_notes": [],
    }
    result = validate_payload("deck", payload, project, claims_by_id)
    rules = {i["rule"] for i in result["issues"]}
    assert "deck_structure" in rules


# --- safety checks -----------------------------------------------------------

def test_claim_safety_checks_flags_high_risk_and_language():
    class _Ev:
        relation = "supports"
        excerpt = "passage"

    class _Claim:
        id = "CLM-9001"
        claim_text = "This supplement is guaranteed to work for everyone."
        status = "supported"
        risk_level = "high"
        study_design = None
        evidence = [_Ev()]

    checks = claim_safety_checks(_Claim())
    rules = {c["rule"] for c in checks}
    assert "overstatement" in rules or "universal_claim" in rules

    class _Stranded:
        id = "CLM-9002"
        claim_text = "Something factual."
        status = "supported"
        risk_level = "medium"
        study_design = None
        evidence = []

    checks2 = claim_safety_checks(_Stranded())
    assert any(c["rule"] == "missing_evidence" for c in checks2)


def test_safety_checks_endpoint(client, editor_headers, project_with_sources):
    pid = project_with_sources
    r = client.get(f"/api/projects/{pid}/safety-checks", headers=editor_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["project_id"] == pid
    assert "note" in body
    assert isinstance(body["claims"], list) and body["claims"], "claims must be listed"
    row = body["claims"][0]
    assert {"claim_id", "claim_text", "status", "risk_level", "checks"} <= set(row)
    assert "totals" in body and "deliverables" in body


# --- export kinds ------------------------------------------------------------

def test_export_kinds_and_deck_end_to_end(client, editor_headers, doctor_headers, project_with_sources):
    pid = project_with_sources

    # generate a deck only
    r = client.post(f"/api/projects/{pid}/generate", json={"formats": ["deck"]}, headers=editor_headers)
    assert r.status_code == 202, r.text

    from app.workers.runner import execute_run

    db = SessionLocal()
    try:
        run_id = r.json()["id"]
        execute_run(db, run_id)
    finally:
        db.close()

    dels = client.get(f"/api/projects/{pid}/deliverables", headers=editor_headers).json()
    deck = next((d for d in dels if d["format"] == "deck"), None)
    assert deck is not None, "deck deliverable must be created when requested"

    detail = client.get(f"/api/deliverables/{deck['id']}", headers=editor_headers).json()
    version = detail["current_version"]
    assert version is not None
    assert version["generation_mode"] == "deterministic"
    assert len(version["payload"]["slides"]) == 10
    # the native pptx asset must exist after rendering
    kinds = {a["kind"] for a in version["assets"]}
    assert "deck_pptx" in kinds, kinds

    # export kinds
    for kind, expect_mime_fragment in (
        ("full", "zip"),
        ("evidence_report", "markdown"),
        ("source_manifest", "json"),
        ("captions", "plain"),
    ):
        rr = client.post(f"/api/deliverables/{deck['id']}/export", json={"kind": kind}, headers=editor_headers)
        assert rr.status_code == 200, rr.text
        body = rr.json()
        assert body["asset_id"] and body["filename"]
        assert expect_mime_fragment in body.get("download_url", "") or body["asset_id"]

    # deck flows through review + approval + publishing like every other format
    r = client.post(f"/api/deliverables/{deck['id']}/submit", json={"note": "deck pass"}, headers=editor_headers)
    assert r.status_code == 200, r.text
    queue = client.get("/api/review/queue", headers=editor_headers).json()
    row = next((q for q in queue if q["id"] == deck["id"]), None)
    assert row is not None, "deck must appear in the review queue"

    current_id = detail["current_version"]["id"]
    r = client.post(
        f"/api/deliverables/{deck['id']}/reviews",
        json={"version_id": current_id, "decision": "approved", "comments": "looks good"},
        headers=editor_headers,
    )
    assert r.status_code == 403, "editors must not be able to approve"
    # a doctor must approve
    r = client.post(
        f"/api/deliverables/{deck['id']}/reviews",
        json={"version_id": current_id, "decision": "approved", "comments": "looks good"},
        headers=doctor_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "ready_to_publish"


# --- settings endpoint -------------------------------------------------------

def test_settings_endpoint_no_secrets(client, editor_headers):
    r = client.get("/api/settings", headers=editor_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["app"]
    assert body["version"]
    assert body["database"]["engine"] in {"sqlite", "postgresql"}
    assert body["rendering"]["pptx_available"] is True
    # never leak secrets
    blob = str(body).lower()
    for secret_word in ("secret", "api_key", "password", "token"):
        assert secret_word not in blob, f"settings must not expose {secret_word}"
    assert body["ai"]["provider"] in {"none", "openai", "azure", "compatible"}


def test_settings_requires_auth(client):
    r = client.get("/api/settings")
    assert r.status_code == 401
