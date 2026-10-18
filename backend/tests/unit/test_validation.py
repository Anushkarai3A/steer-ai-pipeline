from __future__ import annotations

import pytest

from app.core.database import SessionLocal
from app.core.ids import new_id
from app.models import ClaimEvidence, EvidenceClaim, ResearchProject, ResearchSource
from app.schemas.content import CarouselPayload, ReelPayload, StaticPayload, payload_model_for
from app.services.content_generation import fallback
from app.services.validation.validate import has_blocking_errors, validate_payload


def _project(db, claims_spec: list[dict]) -> tuple[ResearchProject, dict]:
    project = ResearchProject(id=new_id("prj"), name="Validation test", description="")
    db.add(project)
    db.flush()
    db.query(ResearchSource).filter(ResearchSource.id == "src1").delete()
    db.flush()
    db.add(ResearchSource(id="src1", project_id=project.id, title="Source One", year=2023, status="extracted"))
    db.flush()
    for spec in claims_spec:
        # ids are global; clear any prior row from an earlier test (rolled back on teardown)
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
                    source_id="src1",
                    relation="supports",
                    excerpt=ev_text,
                    page=1,
                )
            )
        db.add(claim)
    db.flush()
    db.refresh(project)
    return project, {c.id: c for c in project.claims}


def _payload(carousel=True):
    if carousel:
        return {
            "concept": "c", "audience": "a", "main_message": "m",
            "slides": [
                {"index": 0, "headline": "Hook", "body": "Body", "claim_ids": ["CLM-0001"], "footnote": "f"},
                {"index": 1, "headline": "Second", "body": "More", "claim_ids": ["CLM-0001"], "footnote": "f"},
                {"index": 2, "headline": "Nuance", "body": "Limitations here", "claim_ids": []},
                {"index": 3, "headline": "Close", "body": "Takeaway", "claim_ids": ["CLM-0001"]},
            ],
            "caption": "Caption with 8.2 mmHg detail",
            "hashtags": ["#x"],
            "source_notes": [{"text": "Source One 2023 p.2", "source_id": "src1"}],
            "limitations": ["Small sample"],
            "disclaimer": "This is educational and is not medical advice.",
        }
    return None


def test_payload_schema_rejects_bad_reel():
    with pytest.raises(Exception):
        ReelPayload.model_validate({
            "duration_seconds": 30,
            "hook": "h",
            "scenes": [
                {"index": 5, "start_seconds": 0, "end_seconds": 3, "on_screen_text": "x", "voiceover": "y"},
            ],
        })


def test_payload_schema_accepts_valid_carousel():
    p = CarouselPayload.model_validate(_payload())
    assert len(p.slides) == 4
    assert payload_model_for("static") is StaticPayload


def test_validation_passes_for_well_linked_content(db_session):
    project, claims = _project(db_session, [{
        "id": "CLM-0001",
        "claim_text": "Resting systolic blood pressure fell by 8.2 mmHg in the intervention group.",
        "evidence": ["Resting systolic blood pressure fell by 8.2 mmHg in the intervention group."],
        "status": "supported",
    }])
    result = validate_payload("carousel", _payload(), project, claims)
    assert result["status"] == "passed", result["issues"]


def test_validation_flags_unknown_claim_id(db_session):
    project, claims = _project(db_session, [{
        "id": "CLM-0001", "claim_text": "x", "evidence": ["x"], "status": "supported",
    }])
    payload = _payload()
    payload["slides"][0]["claim_ids"] = ["CLM-9999"]
    result = validate_payload("carousel", payload, project, claims)
    rules = [i["rule"] for i in result["issues"] if i["severity"] == "error"]
    assert "citation_integrity" in rules
    assert has_blocking_errors(result)


def test_validation_blocks_unsupported_claim_usage(db_session):
    project, claims = _project(db_session, [{
        "id": "CLM-0001", "claim_text": "x", "evidence": [], "status": "unsupported",
    }])
    result = validate_payload("carousel", _payload(), project, claims)
    assert any(i["rule"] == "evidence_status" and i["severity"] == "error" for i in result["issues"])
    assert has_blocking_errors(result)


def test_validation_blocks_unresolved_high_risk_claim(db_session):
    project, claims = _project(db_session, [{
        "id": "CLM-0001", "claim_text": "x", "evidence": [], "status": "needs_human_review",
        "risk_level": "high",
    }])
    result = validate_payload("carousel", _payload(), project, claims)
    assert has_blocking_errors(result)


def test_validation_requires_caveats_and_disclaimer(db_session):
    project, claims = _project(db_session, [{
        "id": "CLM-0001", "claim_text": "x", "evidence": ["x"], "status": "supported",
    }])
    payload = _payload()
    payload["limitations"] = []
    payload["disclaimer"] = ""
    result = validate_payload("carousel", payload, project, claims)
    rules = {i["rule"] for i in result["issues"] if i["severity"] == "error"}
    assert "required_caveats" in rules and "required_disclaimer" in rules


def test_validation_flags_overclaim_and_shame_language(db_session):
    project, claims = _project(db_session, [{
        "id": "CLM-0001", "claim_text": "x", "evidence": ["x"], "status": "supported",
    }])
    payload = _payload()
    payload["slides"][1]["body"] = "This proven cure guarantees results for everyone."
    payload["slides"][2]["body"] = "Stop being lazy about your health."
    result = validate_payload("carousel", payload, project, claims)
    rules = {i["rule"] for i in result["issues"]}
    assert "overstatement" in rules
    assert "fear_shame" in rules


def test_validation_flags_medication_recommendation(db_session):
    project, claims = _project(db_session, [{
        "id": "CLM-0001", "claim_text": "x", "evidence": ["x"], "status": "supported",
    }])
    payload = _payload()
    payload["slides"][1]["body"] = "Ask your doctor for metformin today."
    result = validate_payload("carousel", payload, project, claims)
    assert any(i["rule"] == "medication_advice" for i in result["issues"])


def test_validation_flags_fabricated_statistic(db_session):
    project, claims = _project(db_session, [{
        "id": "CLM-0001",
        "claim_text": "Blood pressure fell by 8.2 mmHg in the program group.",
        "evidence": ["Blood pressure fell by 8.2 mmHg in the program group."],
        "status": "supported",
    }])
    payload = _payload()
    payload["slides"][1]["body"] = "Risk dropped by 73.5% within two weeks."
    payload["slides"][1]["claim_ids"] = ["CLM-0001"]
    result = validate_payload("carousel", payload, project, claims)
    assert any(i["rule"] == "fabricated_statistic" for i in result["issues"])


def test_validation_flags_causal_language_from_observational_claim(db_session):
    project, claims = _project(db_session, [{
        "id": "CLM-0001",
        "claim_text": "Self-monitoring was associated with fewer cardiovascular events.",
        "evidence": ["Self-monitoring was associated with fewer cardiovascular events."],
        "status": "supported",
        "study_design": "prospective cohort study, cross-sectional elements",
    }])
    payload = _payload()
    payload["slides"][1]["body"] = "Self-monitoring reduces cardiovascular risk."
    payload["slides"][1]["claim_ids"] = ["CLM-0001"]
    result = validate_payload("carousel", payload, project, claims)
    assert any(i["rule"] == "causal_overreach" for i in result["issues"])


def test_fallback_generators_produce_schema_valid_payloads(db_session):
    project, claims = _project(db_session, [{
        "id": "CLM-0001",
        "claim_text": "Resting systolic blood pressure fell by 8.2 mmHg after the program.",
        "evidence": ["Resting systolic blood pressure fell by 8.2 mmHg after the program."],
        "status": "supported",
        "limitations": "Short follow-up.",
    }])
    claim_dicts = [{
        "id": c.id, "claim_text": c.claim_text, "status": c.status, "risk_level": c.risk_level,
        "population": c.population, "study_design": c.study_design, "effect_size": None,
        "limitations": c.limitations,
        "evidence": [{"source_id": "src1", "excerpt": e.excerpt, "page": e.page, "doi": None,
                      "url": None, "source": {"title": "Source One", "journal": "J", "year": 2023}} for e in c.evidence],
    } for c in project.claims]
    summary = {"limitations": [{"text": "Short follow-up."}], "key_findings": []}

    for fmt, builder in (("carousel", fallback.build_carousel), ("static", fallback.build_static),
                         ("reel", fallback.build_reel)):
        payload = builder(project.name, summary, claim_dicts, [{"id": "src1", "title": "Source One"}])
        model = payload_model_for(fmt).model_validate(payload)
        assert model.limitations, f"{fmt} must include limitations"
        assert "not medical advice" in model.disclaimer.lower()


def test_fallback_refuses_without_linked_claims(db_session):
    project, claims = _project(db_session, [{
        "id": "CLM-0001", "claim_text": "x", "evidence": [], "status": "unsupported",
    }])
    claim_dicts = [{"id": "CLM-0001", "claim_text": "x", "status": "unsupported", "evidence": []}]
    with pytest.raises(ValueError):
        fallback.build_carousel(project.name, {"limitations": []}, claim_dicts, [])
