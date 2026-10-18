from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Environment MUST be configured before any app import.
_TMP = Path(tempfile.mkdtemp(prefix="steer_tests_"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["GENERATED_DIR"] = str(_TMP / "generated")
os.environ["LLM_PROVIDER"] = "none"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["ENVIRONMENT"] = "test"

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import fitz  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def make_pdf(pages: list[str]) -> bytes:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page(width=595, height=842)
        page.insert_textbox(fitz.Rect(50, 50, 545, 800), text, fontsize=11, fontname="tiro")
    data = doc.tobytes()
    doc.close()
    return data


PAPER_A_PAGES = [
    (
        "Effect of a structured breathing program on resting blood pressure: a randomized trial\n\n"
        "Abstract\n\n"
        "Elevated blood pressure is common in adults. We tested whether a structured breathing "
        "program changes resting systolic blood pressure. In this randomized controlled trial, "
        "120 adults with elevated systolic blood pressure were assigned to the program or to "
        "usual care for 12 weeks."
    ),
    (
        "Methods\n\n"
        "120 adults aged 45 to 70 with elevated systolic blood pressure were randomly assigned "
        "to a structured breathing program or usual care. Resting systolic blood pressure was "
        "measured by a blinded assessor at baseline and week 12.\n\n"
        "Results\n\n"
        "After 12 weeks, the intervention group had a mean change in resting systolic blood "
        "pressure of -8.2 mmHg (95% CI -11.0 to -5.4) compared with -1.5 mmHg in the control "
        "group. The between-group difference was -6.7 mmHg (95% CI -9.8 to -3.6). "
        "Adherence averaged 84% of scheduled sessions across the intervention group."
    ),
    (
        "Discussion\n\n"
        "A structured breathing program was associated with a larger reduction in resting "
        "systolic blood pressure than usual care over 12 weeks.\n\n"
        "Limitations: this trial had a small sample and a short 12-week follow-up, and the "
        "findings may not generalize to adults with other health conditions. Because the "
        "intervention was not blinded, measurement bias cannot be excluded. The trial "
        "establishes nothing about long-term cardiovascular events."
    ),
]

PAPER_B_PAGES = [
    (
        "Home monitoring of blood pressure: a cohort analysis\n\n"
        "Abstract\n\n"
        "We examined whether self-monitored blood pressure is associated with later heart "
        "outcomes in 4,500 adults followed for 5 years. This was a prospective cohort study "
        "and cannot establish causation."
    ),
    (
        "Results\n\n"
        "Adults who self-monitored blood pressure had a 14% lower rate of the composite "
        "cardiovascular outcome over 5 years (HR 0.86, 95% CI 0.75 to 0.98) after adjustment. "
        "No association was observed for all-cause hospital admission (HR 1.02, 95% CI 0.92 "
        "to 1.13).\n\n"
        "Discussion\n\n"
        "Self-monitoring was associated with fewer cardiovascular events, but residual "
        "confounding is likely. Limitations: adherence was self-reported and the cohort was "
        "not randomized, so the association does not prove that monitoring reduces risk.",
    ),
]


@pytest.fixture(scope="session")
def app_ready():
    from app.core.database import init_db
    from app.main import seed_users

    init_db()
    seed_users()
    yield


@pytest.fixture(scope="session")
def client(app_ready):
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def editor_headers(client):
    r = client.post("/api/auth/login", json={"email": "editor@steer.demo", "password": "demo1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def doctor_headers(client):
    r = client.post("/api/auth/login", json={"email": "doctor@steer.demo", "password": "demo1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def db_session(app_ready):
    from app.core.database import SessionLocal

    db = SessionLocal()
    yield db
    db.rollback()
    db.close()


@pytest.fixture()
def project_with_sources(client, editor_headers):
    """Create a project with two extracted sources and run the pipeline synchronously."""
    from app.core.database import SessionLocal
    from app.models import ResearchProject
    from app.workers.runner import create_run, execute_run

    r = client.post(
        "/api/projects",
        json={"name": "BP pipeline test", "description": "test"},
        headers=editor_headers,
    )
    assert r.status_code == 201, r.text
    project_id = r.json()["id"]

    for pages in (PAPER_A_PAGES, PAPER_B_PAGES):
        resp = client.post(
            f"/api/projects/{project_id}/sources",
            files={"file": ("paper.pdf", make_pdf(pages), "application/pdf")},
            headers=editor_headers,
        )
        assert resp.status_code == 201, resp.text

    db = SessionLocal()
    try:
        project = db.get(ResearchProject, project_id)
        run = create_run(db, project, "full")
        run = execute_run(db, run.id)
        assert run.status == "succeeded", run.error
    finally:
        db.close()
    return project_id
