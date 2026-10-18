from __future__ import annotations

import time

from app.core.database import SessionLocal
from app.models import ContentDeliverable, PipelineRun, ProjectStatus, ResearchProject, ResearchSource
from app.workers.runner import create_run, execute_run


def _generate_sync(project_id: str) -> None:
    db = SessionLocal()
    try:
        project = db.get(ResearchProject, project_id)
        run = create_run(db, project, "generation")
        run = execute_run(db, run.id)
        assert run.status == "succeeded", run.error
    finally:
        db.close()


def _current_version_id(client, deliverable_id, headers) -> str:
    detail = client.get(f"/api/deliverables/{deliverable_id}", headers=headers).json()
    return detail["current_version"]["id"]


def test_full_demo_workflow(project_with_sources, client, editor_headers, doctor_headers):
    pid = project_with_sources

    # --- evidence lab -----------------------------------------------------
    claims = client.get(f"/api/projects/{pid}/claims", headers=editor_headers).json()
    assert len(claims) >= 3
    with_evidence = [c for c in claims if c["evidence"]]
    assert with_evidence, "at least one claim must have located evidence"
    ev = with_evidence[0]["evidence"][0]
    excerpt = client.get(f"/api/evidence/{ev['id']}/excerpt", headers=editor_headers)
    assert excerpt.status_code == 200
    body = excerpt.json()
    assert body["excerpt"].strip()
    assert body["source_id"], "excerpt must identify its source"

    # --- generation --------------------------------------------------------
    _generate_sync(pid)
    dels = client.get(f"/api/projects/{pid}/deliverables", headers=editor_headers).json()
    assert {d["format"] for d in dels} == {"carousel", "static", "reel"}

    carousel = next(d for d in dels if d["format"] == "carousel")
    detail = client.get(f"/api/deliverables/{carousel['id']}", headers=editor_headers).json()
    assert detail["current_version"] is not None
    version = detail["current_version"]
    assert version["generation_mode"] == "deterministic"
    assert "deterministic" in version["generation_mode_label"].lower()
    assert version["validation"]["status"] in {"passed", "warnings"}, version["validation"]
    assert version["assets"], "rendered assets must exist"
    assert detail["status"] in {"draft", "needs_evidence_review"}

    # downloads are real files (RULE 9: assets correspond to saved version)
    asset = next(a for a in version["assets"] if a["kind"] == "carousel_zip")
    dl = client.get(f"/api/assets/{asset['id']}", headers=editor_headers)
    assert dl.status_code == 200
    assert dl.content[:2] == b"PK", "zip download must be a real zip"

    # --- publishing blocked before approval (RULE 3) -----------------------
    queue = client.get("/api/publishing", headers=editor_headers).json()
    assert all(i["status"] != "ready_to_publish" for i in queue)

    # --- submit for review --------------------------------------------------
    r = client.post(f"/api/deliverables/{carousel['id']}/submit", json={"note": "first pass"}, headers=editor_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "awaiting_review"

    # --- editor cannot approve (server-side authorization) ------------------
    forbidden = client.post(
        f"/api/deliverables/{carousel['id']}/reviews",
        json={"decision": "approved", "comments": "lgtm"},
        headers=editor_headers,
    )
    assert forbidden.status_code == 403

    # --- approving a stale version fails ------------------------------------
    current_id = _current_version_id(client, carousel["id"], editor_headers)
    stale = client.post(
        f"/api/deliverables/{carousel['id']}/reviews",
        json={"decision": "approved", "comments": "old version", "version_id": "cv_bogus"},
        headers=doctor_headers,
    )
    assert stale.status_code == 409

    # --- doctor approves current version -------------------------------------
    ok = client.post(
        f"/api/deliverables/{carousel['id']}/reviews",
        json={"decision": "approved", "comments": "Checked evidence.", "version_id": current_id},
        headers=doctor_headers,
    )
    assert ok.status_code == 201, ok.text
    approved = ok.json()
    assert approved["status"] in {"approved", "ready_to_publish"}
    assert approved["approved_version_id"] == current_id

    # --- publishing eligibility after approval --------------------------------
    queue = client.get("/api/publishing", headers=editor_headers).json()
    row = next((q for q in queue if q["deliverable_id"] == carousel["id"]), None)
    assert row is not None, "an approved deliverable must have a publishing row"
    if approved["status"] == "ready_to_publish":
        assert row["status"] == "ready_to_publish"
        assert row["eligible"] is True
    else:
        assert row["status"] == "queued"
        assert row["reasons"], "queued items must explain why they are not ready"

    # --- material edit invalidates approval (RULE 4) --------------------------
    detail = client.get(f"/api/deliverables/{carousel['id']}", headers=editor_headers).json()
    payload = dict(detail["current_version"]["payload"])
    payload["caption"] = payload.get("caption", "") + " Edited after approval."
    edited = client.post(
        f"/api/deliverables/{carousel['id']}/edit",
        json={"payload": payload, "note": "editor tweak"},
        headers=editor_headers,
    )
    assert edited.status_code == 200, edited.text
    edited_body = edited.json()
    assert edited_body["approved_version_id"] is None, "approval must be invalidated"
    assert edited_body["status"] == "awaiting_review", "content must return to review"
    assert edited_body["current_version"]["version_number"] >= 2, "prior approved version must be preserved"
    assert len(edited_body["versions"]) >= 2

    # --- export bundle --------------------------------------------------------
    export = client.post(f"/api/deliverables/{carousel['id']}/export", headers=editor_headers)
    assert export.status_code == 200, export.text
    ed = export.json()
    assert ed["approved"] is False
    zip_resp = client.get(ed["download_url"], headers=editor_headers)
    assert zip_resp.status_code == 200 and zip_resp.content[:2] == b"PK"


def test_rejection_and_changes_requested_flow(project_with_sources, client, editor_headers, doctor_headers):
    pid = project_with_sources
    _generate_sync(pid)
    dels = client.get(f"/api/projects/{pid}/deliverables", headers=editor_headers).json()
    static = next(d for d in dels if d["format"] == "static")

    client.post(f"/api/deliverables/{static['id']}/submit", json={"note": ""}, headers=editor_headers)
    rej = client.post(
        f"/api/deliverables/{static['id']}/reviews",
        json={"decision": "rejected", "comments": "Evidence chain unclear."},
        headers=doctor_headers,
    )
    assert rej.status_code == 201
    assert rej.json()["status"] == "rejected"
    assert rej.json()["approved_version_id"] is None

    # rejected content cannot jump straight to publishing
    queue = client.get("/api/publishing", headers=editor_headers).json()
    row = next((q for q in queue if q["deliverable_id"] == static["id"]), None)
    assert row is None or row["status"] != "ready_to_publish"

    # re-submit then request changes
    client.post(f"/api/deliverables/{static['id']}/submit", json={"note": "second pass"}, headers=editor_headers)
    changes = client.post(
        f"/api/deliverables/{static['id']}/reviews",
        json={"decision": "changes_requested", "comments": "Tighten the caption."},
        headers=doctor_headers,
    )
    assert changes.status_code == 201
    assert changes.json()["status"] == "changes_requested"


def test_failed_pipeline_recovery(client, editor_headers):
    r = client.post("/api/projects", json={"name": "Recovery test", "description": ""}, headers=editor_headers)
    pid = r.json()["id"]
    # corrupt pdf
    client.post(
        f"/api/projects/{pid}/sources",
        files={"file": ("broken.pdf", b"%PDF-1.4 garbage garbage garbage", "application/pdf")},
        headers=editor_headers,
    )

    db = SessionLocal()
    try:
        project = db.get(ResearchProject, pid)
        run = create_run(db, project, "full")
        run = execute_run(db, run.id)
        assert run.status == "failed", "a broken-only project must fail, not fake success (RULE 6)"
        assert run.error and "Stage" in run.error
        failed_stage = next(s for s in run.stages if s.status == "failed")
        assert failed_stage.error, "failed stage must carry a meaningful error"
        assert failed_stage.started_at and failed_stage.finished_at
        skipped = [s for s in run.stages if s.status == "skipped"]
        assert skipped, "later stages must be marked skipped, not completed"
        db.refresh(project)
        assert project.status == ProjectStatus.failed.value

        # recovery: remove the broken source, add a working one, re-run
        broken = project.sources[0]
        from app.services.ingestion import ingest

        ingest.remove_source(db, broken)

        from tests.conftest import PAPER_A_PAGES, make_pdf

        project = db.get(ResearchProject, pid)
        assert project is not None
        db.close()

        upload = client.post(
            f"/api/projects/{pid}/sources",
            files={"file": ("good.pdf", make_pdf(PAPER_A_PAGES), "application/pdf")},
            headers=editor_headers,
        )
        assert upload.status_code == 201

        db = SessionLocal()
        project = db.get(ResearchProject, pid)
        run2 = create_run(db, project, "full")
        run2 = execute_run(db, run2.id)
        assert run2.status == "succeeded", run2.error
        db.refresh(project)
        assert project.status == ProjectStatus.ready.value
    finally:
        db.close()


def test_async_generation_endpoint(project_with_sources, client, editor_headers):
    pid = project_with_sources
    r = client.post(f"/api/projects/{pid}/generate", json={"formats": ["carousel"]}, headers=editor_headers)
    assert r.status_code == 202, r.text
    run_id = r.json()["id"]
    deadline = time.time() + 60
    status = "queued"
    while time.time() < deadline:
        run = client.get(f"/api/pipeline/runs/{run_id}", headers=editor_headers).json()
        status = run["status"]
        if status in {"succeeded", "failed"}:
            break
        time.sleep(0.25)
    assert status == "succeeded", run.get("error")


def test_dashboard_reflects_real_data(project_with_sources, client, editor_headers):
    stats = client.get("/api/dashboard/stats", headers=editor_headers).json()
    assert stats["projects"] >= 1
    assert stats["papers_processed"] >= 2
    assert isinstance(stats["ai_enabled"], bool)
    assert stats["recent_activity"] is not None
    assert all("type" in a and "text" in a for a in stats["recent_activity"])
    assert any(p["project_id"] == project_with_sources for p in stats["pipeline_status"])


def test_sample_project_uses_attributed_sources(client, editor_headers):
    r = client.post("/api/projects/sample", headers=editor_headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["sources"]) >= 2
    for s in body["sources"]:
        assert s["is_sample"] is True
        # real papers must carry real citation metadata (or honestly-empty fields)
        if not body.get("demo_data"):
            assert s["title"] and s["doi"], "real sample sources must be attributed"
            assert s["doi"].startswith("10.")


def test_unsupported_high_risk_claim_blocks_ready_to_publish(project_with_sources, client, editor_headers, doctor_headers):
    """RULE 2: content using an unresolved high-risk claim cannot become ready to publish."""
    pid = project_with_sources
    _generate_sync(pid)
    dels = client.get(f"/api/projects/{pid}/deliverables", headers=editor_headers).json()
    reel = next(d for d in dels if d["format"] == "reel")
    detail = client.get(f"/api/deliverables/{reel['id']}", headers=editor_headers).json()
    used = detail["current_version"]["validation"].get("used_claim_ids", [])
    assert used, "test expects content that uses claims"

    # doctor marks a used claim as unsupported
    resp = client.patch(f"/api/claims/{used[0]}", json={"status": "unsupported"}, headers=doctor_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "unsupported"

    # validation must now block
    v = client.post(f"/api/deliverables/{reel['id']}/validate", headers=editor_headers).json()
    assert v["current_version"]["validation_status"] == "failed"
    assert any(
        i["severity"] == "error" and i.get("claim_id") == used[0]
        for i in v["current_version"]["validation"]["issues"]
    )

    # try to push it through review + publishing
    client.post(f"/api/deliverables/{reel['id']}/submit", json={"note": ""}, headers=editor_headers)
    current = _current_version_id(client, reel["id"], editor_headers)
    appr = client.post(
        f"/api/deliverables/{reel['id']}/reviews",
        json={"decision": "approved", "comments": "approve anyway", "version_id": current},
        headers=doctor_headers,
    )
    assert appr.status_code == 201
    assert appr.json()["status"] == "approved", "approval is a human right even with warnings"
    assert appr.json()["status"] != "ready_to_publish", "blocking validation errors prevent ready-to-publish"

    queue = client.get("/api/publishing", headers=editor_headers).json()
    row = next((q for q in queue if q["deliverable_id"] == reel["id"]), None)
    assert row is not None
    assert row["status"] == "queued", "RULE 2: unresolved claims block the ready-to-publish state"
    assert row["eligible"] is False
    assert any("validation" in r.lower() or "unsupported" in r.lower() for r in row["reasons"])


def test_api_error_shapes(client, editor_headers):
    # unauthenticated
    r = client.get("/api/projects")
    assert r.status_code == 401
    assert "detail" in r.json()
    # unknown project
    r = client.get("/api/projects/prj_missing", headers=editor_headers)
    assert r.status_code == 404
    # validation error shape
    r = client.post("/api/projects", json={"name": ""}, headers=editor_headers)
    assert r.status_code == 422
    body = r.json()
    assert "errors" in body
    # unknown deliverable
    r = client.get("/api/deliverables/dlv_missing", headers=editor_headers)
    assert r.status_code == 404
