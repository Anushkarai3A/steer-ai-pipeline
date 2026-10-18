from __future__ import annotations

import io

from tests.conftest import PAPER_A_PAGES, make_pdf


def test_upload_rejects_non_pdf(client, editor_headers):
    r = client.post(
        "/api/projects",
        json={"name": "Bad uploads", "description": ""},
        headers=editor_headers,
    )
    project_id = r.json()["id"]
    resp = client.post(
        f"/api/projects/{project_id}/sources",
        files={"file": ("notes.txt", b"hello world", "text/plain")},
        headers=editor_headers,
    )
    assert resp.status_code == 400
    assert "pdf" in resp.json()["detail"].lower()


def test_upload_rejects_empty_file(client, editor_headers):
    r = client.post("/api/projects", json={"name": "Empty upload", "description": ""}, headers=editor_headers)
    project_id = r.json()["id"]
    resp = client.post(
        f"/api/projects/{project_id}/sources",
        files={"file": ("empty.pdf", b"", "application/pdf")},
        headers=editor_headers,
    )
    assert resp.status_code == 400


def test_upload_rejects_corrupt_pdf(client, editor_headers):
    r = client.post("/api/projects", json={"name": "Corrupt upload", "description": ""}, headers=editor_headers)
    project_id = r.json()["id"]
    resp = client.post(
        f"/api/projects/{project_id}/sources",
        files={"file": ("broken.pdf", b"%PDF-1.4 this is not really a pdf body", "application/pdf")},
        headers=editor_headers,
    )
    # stored as uploaded; extraction must fail with an honest error later (RULE 6)
    assert resp.status_code == 201


def test_duplicate_upload_rejected(client, editor_headers):
    r = client.post("/api/projects", json={"name": "Dedup project", "description": ""}, headers=editor_headers)
    project_id = r.json()["id"]
    pdf = make_pdf(PAPER_A_PAGES)
    first = client.post(
        f"/api/projects/{project_id}/sources",
        files={"file": ("a.pdf", pdf, "application/pdf")},
        headers=editor_headers,
    )
    assert first.status_code == 201
    second = client.post(
        f"/api/projects/{project_id}/sources",
        files={"file": ("a-copy.pdf", pdf, "application/pdf")},
        headers=editor_headers,
    )
    assert second.status_code == 409
    assert "duplicate" in second.json()["detail"].lower()


def test_max_three_sources(client, editor_headers):
    r = client.post("/api/projects", json={"name": "Cap project", "description": ""}, headers=editor_headers)
    project_id = r.json()["id"]
    codes = []
    for i in range(4):
        pdf = make_pdf([f"Unique paper number {i}. " + "Body text " * 50])
        resp = client.post(
            f"/api/projects/{project_id}/sources",
            files={"file": (f"p{i}.pdf", pdf, "application/pdf")},
            headers=editor_headers,
        )
        codes.append(resp.status_code)
    assert codes[:3] == [201, 201, 201]
    assert codes[3] == 400


def test_pdf_extraction_preserves_page_boundaries():
    from app.services.extraction.pdf_extractor import extract_pdf
    from pathlib import Path
    import tempfile

    pdf = make_pdf(["Page one about methods.", "Page two about results.", "Page three about discussion."])
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf)
        path = f.name
    result = extract_pdf(path)
    assert result["page_count"] == 3
    assert [p["page"] for p in result["pages"]] == [1, 2, 3]
    assert "methods" in result["pages"][0]["text"].lower()
    assert "results" in result["pages"][1]["text"].lower()


def test_extraction_fails_on_textless_pdf():
    import fitz
    from app.services.extraction.pdf_extractor import ExtractionError, extract_pdf
    import tempfile

    doc = fitz.open()
    doc.new_page()  # completely empty page
    data = doc.tobytes()
    doc.close()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(data)
        path = f.name
    try:
        extract_pdf(path)
        raise AssertionError("expected ExtractionError")
    except ExtractionError as exc:
        msg = str(exc).lower()
        assert "text" in msg or "scanned" in msg


def test_extraction_fails_on_missing_file():
    from app.services.extraction.pdf_extractor import ExtractionError, extract_pdf

    try:
        extract_pdf("/nonexistent/file.pdf")
        raise AssertionError("expected ExtractionError")
    except ExtractionError:
        pass


def test_missing_metadata_not_fabricated(client, editor_headers):
    """A PDF with no DOI/title metadata must leave those fields empty, not invented."""
    from app.core.database import SessionLocal
    from app.models import ResearchProject, ResearchSource
    from app.workers.runner import create_run, execute_run

    r = client.post("/api/projects", json={"name": "Meta test", "description": ""}, headers=editor_headers)
    project_id = r.json()["id"]
    pdf = make_pdf([
        "An anonymous manuscript with no embedded metadata.\n\nMethods\n\nWe observed 40 participants.",
        "Results\n\nValues increased by 12 units on average.\n\nDiscussion\n\nLimitations: unknown sample provenance.",
    ])
    resp = client.post(
        f"/api/projects/{project_id}/sources",
        files={"file": ("anon.pdf", pdf, "application/pdf")},
        headers=editor_headers,
    )
    assert resp.status_code == 201

    db = SessionLocal()
    try:
        project = db.get(ResearchProject, project_id)
        run = create_run(db, project, "extraction")
        run = execute_run(db, run.id)
        assert run.status == "succeeded", run.error
        source = project.sources[0]
        assert source.doi is None, "DOI must stay empty when not present"
        assert source.journal is None, "journal must stay empty when unknown"
        # title falls back to filename stem — that is honest, derived from the filename
        assert source.title
        assert source.page_count == 2
        assert source.char_count and source.char_count > 0
    finally:
        db.close()


def test_doi_source_without_open_access_is_not_faked(client, editor_headers):
    r = client.post("/api/projects", json={"name": "DOI test", "description": ""}, headers=editor_headers)
    project_id = r.json()["id"]
    resp = client.post(
        f"/api/projects/{project_id}/sources/reference",
        json={"kind": "doi", "doi": "10.1371/journal.pone.0337232"},
        headers=editor_headers,
    )
    assert resp.status_code == 201, resp.text
    source_id = resp.json()["id"]

    from app.core.database import SessionLocal
    from app.models import ResearchProject
    from app.workers.runner import create_run, execute_run

    db = SessionLocal()
    try:
        project = db.get(ResearchProject, project_id)
        run = create_run(db, project, "extraction")
        run = execute_run(db, run.id)
        source = next(s for s in project.sources if s.id == source_id)
        if run.status == "succeeded":
            # either an open PDF was fetched or metadata-only with clear status
            assert source.status in {"extracted", "unsupported"}
            if source.status == "unsupported":
                assert source.error, "unsupported sources must carry an explanation"
                e = source.error.lower()
                assert any(k in e for k in ("paywall", "openly", "network", "resolve"))
        else:
            # offline: extraction stage must FAIL honestly rather than fake content
            assert run.status == "failed"
            assert run.error
    finally:
        db.close()


def test_invalid_doi_rejected(client, editor_headers):
    r = client.post("/api/projects", json={"name": "Bad DOI", "description": ""}, headers=editor_headers)
    project_id = r.json()["id"]
    resp = client.post(
        f"/api/projects/{project_id}/sources/reference",
        json={"kind": "doi", "doi": "not-a-doi"},
        headers=editor_headers,
    )
    assert resp.status_code == 400
