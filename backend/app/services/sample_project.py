from __future__ import annotations

"""Sample project creation.

Preferred path: three REAL open-access papers downloaded by
scripts/fetch_sample_sources.py into samples/ (PLOS, CC-licensed, full
attribution in samples/ATTRIBUTION.json). The sample project then contains
genuinely published research with real metadata.

Fallback path (offline): two clearly-labelled SYNTHETIC papers whose every
page is marked "DEMO DATA — NOT REAL RESEARCH", so nobody can mistake the
demonstration for real findings. The UI shows a DEMO DATA badge for these.
"""

import hashlib
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT, settings
from app.core.ids import new_id
from app.models import ProjectStatus, ResearchProject, ResearchSource, SourceStatus, User

SAMPLES_DIR = REPO_ROOT / "samples"


def create_sample_project(db: Session, user: User | None = None) -> ResearchProject:
    attribution = _load_attribution()
    real_files = [a for a in attribution if (SAMPLES_DIR / a["file"]).exists()]

    if len(real_files) >= 2:
        project = _existing(db, "Sample project")
        if project:
            return project
        project = _new_project(
            db, user,
            name="Sample: sleep duration & cardiometabolic health",
            description=(
                "Sample project built from real open-access research papers (PLOS, Creative "
                "Commons). Full citation and licence metadata are stored on each source. "
                "Generated content still requires doctor review before any use."
            ),
            demo_data=False,
        )
        for a in real_files:
            _add_real_source(db, project, a)
        return project

    # Offline fallback: synthetic, loudly labelled DEMO DATA.
    project = _existing(db, "DEMO DATA")
    if project:
        return project
    project = _new_project(
        db, user,
        name="DEMO DATA — interface demonstration (synthetic sources)",
        description=(
            "DEMO DATA: these sources are synthetic documents created only to demonstrate the "
            "Steer interface offline. They are NOT real research and must never be cited or "
            "published as health information."
        ),
        demo_data=True,
    )
    for text in (_synthetic_paper_one(), _synthetic_paper_two()):
        _add_synthetic_source(db, project, text)
    return project


def _load_attribution() -> list[dict]:
    path = SAMPLES_DIR / "ATTRIBUTION.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _existing(db: Session, name_prefix: str) -> ResearchProject | None:
    for p in db.query(ResearchProject).all():
        if p.name.startswith(name_prefix) and p.sources:
            return p
    return None


def _new_project(db: Session, user: User | None, *, name: str, description: str, demo_data: bool) -> ResearchProject:
    project = ResearchProject(
        id=new_id("prj"),
        name=name,
        description=description,
        demo_data=demo_data,
        created_by=user.id if user else None,
        status=ProjectStatus.draft.value,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _add_real_source(db: Session, project: ResearchProject, a: dict) -> None:
    data = (SAMPLES_DIR / a["file"]).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if any(s.sha256 == sha for s in project.sources):
        return
    source_id = new_id("src")
    dest_dir = settings.upload_path / project.id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{source_id}.pdf"
    dest.write_bytes(data)
    db.add(
        ResearchSource(
            id=source_id,
            project_id=project.id,
            kind="pdf",
            original_filename=a["file"],
            file_path=str(dest),
            sha256=sha,
            byte_size=len(data),
            title=a.get("title"),
            authors=a.get("authors"),
            year=int(a["year"]) if a.get("year") else None,
            journal=a.get("journal"),
            doi=a.get("doi"),
            canonical_url=a.get("url"),
            status=SourceStatus.uploaded.value,
            is_sample=True,
        )
    )
    db.commit()
    db.expire(project, ["sources"])


def _add_synthetic_source(db: Session, project: ResearchProject, paper: dict) -> None:
    pdf_bytes = _render_synthetic_pdf(paper["title"], paper["pages"])
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    if any(s.sha256 == sha for s in project.sources):
        return
    source_id = new_id("src")
    dest_dir = settings.upload_path / project.id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{source_id}.pdf"
    dest.write_bytes(pdf_bytes)
    db.add(
        ResearchSource(
            id=source_id,
            project_id=project.id,
            kind="pdf",
            original_filename=paper["filename"],
            file_path=str(dest),
            sha256=sha,
            byte_size=len(pdf_bytes),
            title=paper["title"],
            authors=paper["authors"],
            year=paper["year"],
            journal="DEMO DATA — synthetic journal (not real)",
            status=SourceStatus.uploaded.value,
            is_sample=True,
        )
    )
    db.commit()
    db.expire(project, ["sources"])


def _render_synthetic_pdf(title: str, pages: list[str]) -> bytes:
    import fitz

    doc = fitz.open()
    for i, text in enumerate(pages, start=1):
        page = doc.new_page(width=595, height=842)
        page.insert_text((60, 50), "DEMO DATA — SYNTHETIC SAMPLE, NOT REAL RESEARCH",
                         fontsize=9, fontname="helv", color=(0.75, 0.3, 0.2))
        page.insert_textbox(
            fitz.Rect(60, 70, 535, 790),
            text,
            fontsize=10.5,
            fontname="tiro",
            align=fitz.TEXT_ALIGN_LEFT,
        )
        page.insert_text((60, 815), f"{title} — page {i} — steer demo", fontsize=8, fontname="helv")
    data = doc.tobytes()
    doc.close()
    return data


# --- synthetic content (loudly labelled) -----------------------------------

_DEMO_BANNER = (
    "DEMO DATA. This document is synthetic fiction written to demonstrate the Steer "
    "interface. It is not a real study, contains no real findings, and must never be "
    "cited, published, or used for health decisions."
)


def _synthetic_paper_one() -> dict:
    title = "DEMO DATA — Synthetic Paper A (fiction): Evening screen habits and self-reported alertness"
    pages = [
        f"{title}\n\n{_DEMO_BANNER}\n\nAbstract\n\n"
        "This synthetic document describes a fictional survey of 500 fictional adults. "
        "In the fictional dataset, participants who reported a consistent evening wind-down "
        "routine scored 12 points higher on a fictional alertness scale (95% CI 6 to 18) than "
        "participants who did not. The design is fictional and cross-sectional, so the fictional "
        "association cannot establish cause and effect.\n\n"
        "Keywords: demo data, synthetic, cross-sectional",

        f"{title}\n\n{_DEMO_BANNER}\n\nMethods\n\n"
        "500 fictional adults aged 30 to 60 were invented for this demonstration. "
        "A fictional questionnaire recorded self-reported routines and alertness. "
        "No real people, real measurements or real ethics approvals are involved.\n\n"
        "Results\n\n"
        "In the fictional dataset, 62% of participants with a wind-down routine reported "
        "good next-day alertness versus 41% without (fictional difference: 21 percentage points). "
        "Average fictional sleep onset was 22 minutes shorter in the wind-down group. "
        "No statistical test was actually performed; these numbers are invented for the demo.",

        f"{title}\n\n{_DEMO_BANNER}\n\nDiscussion\n\n"
        "These fictional results suggest a possible association, but the synthetic design "
        "cannot establish that wind-down routines cause alertness. Limitations: the entire "
        "dataset is fictional, self-reported, and cross-sectional; generalisation is inappropriate. "
        "This demo document establishes nothing about real health.",
    ]
    return {"title": title, "filename": "DEMO_DATA_synthetic_paper_A.pdf", "authors": ["Steer Demo Team (fiction)"],
            "year": 2024, "pages": pages}


def _synthetic_paper_two() -> dict:
    title = "DEMO DATA — Synthetic Paper B (fiction): Contradictory fictional findings on alertness"
    pages = [
        f"{title}\n\n{_DEMO_BANNER}\n\nAbstract\n\n"
        "This second synthetic document exists to demonstrate how Steer surfaces conflicting "
        "sources. In this fictional dataset of 300 fictional adults, no association was found "
        "between evening routines and next-day alertness (fictional OR 1.0, 95% CI 0.7 to 1.4), "
        "inconsistent with the fictional results reported by synthetic Paper A.",

        f"{title}\n\n{_DEMO_BANNER}\n\nMethods\n\n"
        "300 fictional adults were invented for this demonstration. All data are synthetic.\n\n"
        "Results\n\n"
        "In this fictional dataset, alertness scores differed by 1 point between groups "
        "(95% CI -3 to 5), which the fictional authors interpreted as no meaningful association. "
        "These numbers are invented and demonstrate nothing about real health.",

        f"{title}\n\n{_DEMO_BANNER}\n\nDiscussion\n\n"
        "The fictional findings are inconsistent with synthetic Paper A, which the interface "
        "should surface as a conflict rather than picking the more shareable result. "
        "Limitations: everything in this document is fictional; it establishes nothing.",
    ]
    return {"title": title, "filename": "DEMO_DATA_synthetic_paper_B.pdf", "authors": ["Steer Demo Team (fiction)"],
            "year": 2024, "pages": pages}
