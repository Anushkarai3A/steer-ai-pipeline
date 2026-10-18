from __future__ import annotations

import zipfile
from pathlib import Path

from app.services.content_generation import fallback
from app.services.rendering.render_assets import (
    render_carousel,
    render_reel,
    render_static,
    render_version_assets,
)


def _payload(fmt: str) -> dict:
    claims = [{
        "id": "CLM-0001",
        "claim_text": "Resting systolic blood pressure fell by 8.2 mmHg after the program.",
        "status": "supported",
        "risk_level": "medium",
        "population": None,
        "study_design": None,
        "effect_size": None,
        "limitations": "Short follow-up in a small sample.",
        "evidence": [{
            "source_id": "src1",
            "excerpt": "Resting systolic blood pressure fell by 8.2 mmHg after the program.",
            "page": 2,
            "doi": None,
            "url": None,
            "source": {"title": "Sample trial", "journal": "Demo Journal", "year": 2023},
        }],
    }]
    summary = {"limitations": [{"text": "Short follow-up in a small sample."}], "key_findings": []}
    sources = [{"id": "src1", "title": "Sample trial"}]
    return {
        "carousel": lambda: fallback.build_carousel("Render test", summary, claims, sources),
        "static": lambda: fallback.build_static("Render test", summary, claims, sources),
        "reel": lambda: fallback.build_reel("Render test", summary, claims, sources),
    }[fmt]()


def test_carousel_renders_all_slides_and_zip(tmp_path):
    payload = _payload("carousel")
    assets = render_carousel(payload, tmp_path)
    slides = [a for a in assets if a["kind"] == "carousel_slide"]
    zips = [a for a in assets if a["kind"] == "carousel_zip"]
    assert len(slides) == len(payload["slides"])
    for s in slides:
        p = Path(s["path"])
        assert p.exists() and p.stat().st_size > 5_000, "slide PNG must be a real image"
        assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]["path"]) as zf:
        names = zf.namelist()
        assert any(n.startswith("slide_") for n in names)
        assert "caption.txt" in names
        assert "source_notes.txt" in names


def test_static_renders_png(tmp_path):
    payload = _payload("static")
    assets = render_static(payload, tmp_path)
    png = next(a for a in assets if a["kind"] == "static_png")
    p = Path(png["path"])
    assert p.exists() and p.stat().st_size > 5_000
    from PIL import Image

    with Image.open(p) as img:
        assert img.size == (1080, 1080)


def test_reel_renders_storyboard_or_mp4(tmp_path):
    payload = _payload("reel")
    assets = render_reel(payload, tmp_path)
    kinds = {a["kind"] for a in assets}
    assert "storyboard_zip" in kinds
    assert "reel_mp4" in kinds or "storyboard_scene" in kinds
    if "reel_mp4" in kinds:
        mp4 = Path(next(a for a in assets if a["kind"] == "reel_mp4")["path"])
        assert mp4.exists() and mp4.stat().st_size > 2_000
        assert mp4.read_bytes()[4:8] == b"ftyp", "mp4 must have a real container header"
    sb = Path(next(a for a in assets if a["kind"] == "storyboard_zip")["path"])
    assert sb.exists()
    with zipfile.ZipFile(sb) as zf:
        assert "storyboard.txt" in zf.namelist()
        assert any(n.startswith("scene_") for n in zf.namelist())
    # storyboard must be honestly labelled when no mp4 was produced
    if "reel_mp4" not in kinds:
        label = next(a for a in assets if a["kind"] == "storyboard_zip")["label"]
        assert "unavailable" in label.lower() or "storyboard" in label.lower()


def test_render_version_assets_dispatch(tmp_path):
    for fmt in ("carousel", "static", "reel"):
        assets = render_version_assets(fmt, _payload(fmt), tmp_path / fmt)
        assert assets
