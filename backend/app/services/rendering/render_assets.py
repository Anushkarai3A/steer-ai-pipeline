from __future__ import annotations

"""Deterministic asset rendering (Stage 7).

Every downloadable asset is rendered from the saved content version using the
Steer design system (pipeline/templates/design-system.json). Carousel slides
and static posts are high-resolution PNGs; reels are assembled into a vertical
MP4 when ffmpeg is available (bundled via imageio-ffmpeg or on PATH), otherwise
a clearly labelled storyboard package is produced instead — never a fake video.
"""

import shutil
import subprocess
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

from app.core.config import settings
from app.services.rendering.fonts import design_tokens, font, text_width, wrap_to_lines


class RenderError(Exception):
    pass


TOKENS = design_tokens()
C = TOKENS["colors"]


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i: i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _canvas(w: int, h: int, color: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (w, h), _rgb(color))
    return img, ImageDraw.Draw(img)


def _brandmark(d: ImageDraw.ImageDraw, x: int, y: int, color: str, size: int = 40) -> int:
    f = font("bold", size)
    d.text((x, y), TOKENS["brandmark"], font=f, fill=_rgb(color))
    return size


def _chip(d: ImageDraw.ImageDraw, x: int, y: int, text: str, bg: str, fg: str, size: int, pad: int = 16) -> tuple[int, int, int, int]:
    f = font("body", size)
    tw = text_width(d, text, f)
    box = (x, y, int(x + tw + pad * 2), int(y + size + pad * 1.6))
    d.rounded_rectangle(box, radius=999, fill=_rgb(bg))
    d.text((x + pad, y + pad * 0.7), text, font=f, fill=_rgb(fg))
    return box  # type: ignore[return-value]


def _rule(d: ImageDraw.ImageDraw, x0: int, y: int, x1: int, color: str, height: int = 5) -> None:
    d.rectangle((x0, y, x1, y + height), fill=_rgb(color))


def _lines_height(lines: list[str], fnt, spacing: int) -> int:
    ascent, descent = fnt.getmetrics()
    return len(lines) * (ascent + descent + spacing)


def _fit_block(
    d: ImageDraw.ImageDraw,
    text: str,
    role: str,
    max_size: int,
    min_size: int,
    max_width: int,
    max_lines: int,
) -> tuple[list[str], object, int]:
    """Return (lines, font, size) for the largest font that fits without clipping.

    Shrinks the font before ever truncating. Returns the minimum-size lines
    (possibly clipped) only when even the minimum size cannot fit — the caller
    is expected to have already shortened the text via wording.simplify_claim.
    """
    text = " ".join(str(text or "").split())
    if not text:
        return [], font(role, min_size), min_size
    size = max_size
    while size >= min_size:
        f = font(role, size)
        lines = wrap_to_lines(d, text, f, max_width, max_lines)
        # fits if wrapping did not need to truncate (no ellipsis added by wrap)
        if len(lines) <= max_lines and "\u2026" not in lines[-1]:
            ascent, descent = f.getmetrics()
            if len(lines) * (ascent + descent) <= _MAX_BLOCK_H:
                return lines, f, size
        size -= 4
    f = font(role, min_size)
    return wrap_to_lines(d, text, f, max_width, max_lines), f, min_size


# Maximum pixel height of any single text block. Keeps a long body from
# running into the footer band on a 1080px canvas.
_MAX_BLOCK_H = 480


def render_carousel_slide(slide: dict, total: int, out_path: Path) -> None:
    size = TOKENS["sizes"]["carousel"]
    w, h = size["width"], size["height"]
    has_claims = bool(slide.get("claim_ids"))
    is_closing = slide.get("index") == total - 1

    if is_closing:
        bg, fg, accent = C["maroon"], C["cream"], C["blush"]
    elif not has_claims:
        bg, fg, accent = C["blush"], C["ink"], C["rust"]
    else:
        bg, fg, accent = C["cream"], C["ink"], C["rust"]

    img, d = _canvas(w, h, bg)
    pad = 90
    content_w = w - pad * 2

    _brandmark(d, pad, 74, C["rust"] if fg == C["ink"] else C["blush"], 42)
    counter = f"{slide.get('index', 0) + 1:02d} / {total:02d}"
    cf = font("body", 26)
    d.text((w - pad - text_width(d, counter, cf), 84), counter, font=cf,
           fill=_rgb(accent if fg == C["ink"] else C["blush"]))
    _rule(d, pad, 148, w - pad, accent)

    # Reserve the footer band first so content can never reach it.
    footer_top = h - 200
    y = 210

    # Headline: shrink to fit, never truncate.
    hl, hl_f, _ = _fit_block(d, slide.get("headline", ""), "display",
                             size["headline"], 40, content_w, 5)
    d.multiline_text((pad, y), "\n".join(hl), font=hl_f, fill=_rgb(fg), spacing=16)
    y += _lines_height(hl, hl_f, 16) + 40

    # Body: shrink to fit, never truncate; clamp so it cannot reach the footer.
    bl, bl_f, _ = _fit_block(d, slide.get("body", ""), "body",
                             size["body"], 30, content_w, 9)
    d.multiline_text((pad, y), "\n".join(bl), font=bl_f, fill=_rgb(fg), spacing=14)
    y += _lines_height(bl, bl_f, 14) + 30

    # Evidence chip: fixed slot just above the footer, never over the body.
    chip_note = slide.get("footnote") or (
        f"Evidence: {', '.join(slide['claim_ids'])}" if has_claims else ""
    )
    if chip_note:
        chip_y = footer_top - 60
        if chip_y > y:
            _chip(d, pad, chip_y, chip_note,
                  C["paper"] if fg == C["ink"] else C["rust"],
                  fg if fg == C["ink"] else C["cream"], 24)

    foot_f = font("body", 24)
    d.text((pad, h - 96), "From research paper to Instagram.", font=foot_f,
           fill=_rgb(accent if fg == C["ink"] else C["blush"]))
    big = font("display", 58)
    label = f"{slide.get('index', 0) + 1:02d}"
    d.text((w - pad - text_width(d, label, big), h - 128), label, font=big, fill=_rgb(accent))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")


def render_static_post(payload: dict, out_path: Path) -> None:
    size = TOKENS["sizes"]["static"]
    w, h = size["width"], size["height"]
    img, d = _canvas(w, h, C["paper"])
    pad = 90
    content_w = w - pad * 2

    _brandmark(d, pad, 74, C["maroon"], 44)
    fmt_label = font("body", 26)
    d.text((w - pad - text_width(d, "static post", fmt_label), 86), "static post",
           font=fmt_label, fill=_rgb(C["clay"]))
    _rule(d, pad, 152, w - pad, C["rust"], 6)

    # Reserve the disclaimer band at the bottom first.
    disc_f = font("body", 24)
    disc_lines = wrap_to_lines(d, payload.get("disclaimer", ""), disc_f, content_w, 3)
    disc_h = _lines_height(disc_lines, disc_f, 8)
    disc_top = h - 90 - disc_h
    footer_top = disc_top - 40

    y = 230

    hl, hl_f, _ = _fit_block(d, payload.get("headline", ""), "display",
                             size["headline"], 42, content_w, 5)
    d.multiline_text((pad, y), "\n".join(hl), font=hl_f, fill=_rgb(C["maroon"]), spacing=18)
    y += _lines_height(hl, hl_f, 18) + 44

    bl, bl_f, _ = _fit_block(d, payload.get("body", ""), "body",
                             size["body"], 32, content_w, 7)
    d.multiline_text((pad, y), "\n".join(bl), font=bl_f, fill=_rgb(C["ink"]), spacing=16)
    y += _lines_height(bl, bl_f, 16) + 40

    claim_ids = payload.get("claim_ids") or []
    if claim_ids:
        chip_y = footer_top - 60
        if chip_y > y:
            _chip(d, pad, chip_y, f"Evidence: {', '.join(claim_ids)}", C["blush"], C["maroon"], 26)

    d.multiline_text((pad, disc_top), "\n".join(disc_lines), font=disc_f,
                     fill=_rgb(C["clay"]), spacing=8)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")


def render_reel_scene(scene: dict, payload: dict, total_scenes: int, out_path: Path) -> None:
    size = TOKENS["sizes"]["reel"]
    w, h = size["width"], size["height"]
    idx = scene.get("index", 0)
    dark = idx in (0, total_scenes - 1)
    bg = C["maroon"] if dark else C["cream"]
    fg = C["cream"] if dark else C["ink"]
    accent = C["blush"] if dark else C["rust"]

    img, d = _canvas(w, h, bg)
    pad = 90
    content_w = w - pad * 2

    _brandmark(d, pad, 110, accent, 44)
    time_f = font("body", 28)
    tlabel = f"{scene.get('start_seconds', 0):.0f}s – {scene.get('end_seconds', 0):.0f}s"
    d.text((w - pad - text_width(d, tlabel, time_f), 122), tlabel, font=time_f, fill=_rgb(accent))
    _rule(d, pad, 185, w - pad, accent)

    # Header band ends here; body starts just below with a fixed breathing gap.
    body_top = 260
    gap_after_heading = 36

    # Caption bar is reserved at the bottom BEFORE laying out the heading, so
    # the heading can never be pushed into it or clipped by it.
    cap_block_h = 0
    cap_lines: list[str] = []
    cap_f = font("body", size["caption"])
    if payload.get("on_screen_captions", True) and scene.get("voiceover"):
        max_w = content_w - 60
        cap_lines = wrap_to_lines(d, scene["voiceover"], cap_f, max_w, 4)
        cap_block_h = _lines_height(cap_lines, cap_f, 10) + 60
    cap_top = h - 420 - cap_block_h if cap_block_h else h - 420

    # Heading: shrink to fit, never truncate.
    hl, hl_f, _ = _fit_block(d, scene.get("on_screen_text", ""), "display",
                             size["headline"], 46, content_w, 5)
    d.multiline_text((pad, body_top), "\n".join(hl), font=hl_f, fill=_rgb(fg), spacing=18)
    y = body_top + _lines_height(hl, hl_f, 18) + gap_after_heading

    # Evidence chip sits directly under the heading with a consistent gap.
    if scene.get("claim_ids"):
        chip_text = f"Evidence: {', '.join(scene['claim_ids'])}"
        chip_bottom = y + 46
        if chip_bottom < cap_top - 20:
            _chip(d, pad, y, chip_text, accent, C["maroon"] if dark else C["cream"], 26)
            y = chip_bottom + 24

    if cap_block_h:
        d.rounded_rectangle((pad - 10, cap_top, w - pad + 10, cap_top + cap_block_h),
                            radius=24, fill=_rgb(C["ink"] if not dark else "#2b0d0d"))
        d.multiline_text((pad + 20, cap_top + 30), "\n".join(cap_lines),
                         font=cap_f, fill=_rgb(C["cream"]), spacing=10)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")


# --- asset packaging -------------------------------------------------------


def render_carousel(payload: dict, out_dir: Path) -> list[dict]:
    slides = payload.get("slides") or []
    if not slides:
        raise RenderError("Carousel payload has no slides to render.")
    out_dir.mkdir(parents=True, exist_ok=True)
    assets = []
    paths: list[Path] = []
    for i, slide in enumerate(slides, start=1):
        p = out_dir / f"slide_{i:02d}.png"
        render_carousel_slide(slide, len(slides), p)
        paths.append(p)
        assets.append({
            "kind": "carousel_slide",
            "path": str(p),
            "filename": p.name,
            "mime": "image/png",
            "label": f"Slide {i}",
        })

    caption_txt = out_dir / "caption.txt"
    caption_txt.write_text(payload.get("caption", ""), encoding="utf-8")
    sources_txt = out_dir / "source_notes.txt"
    sources_txt.write_text(
        "\n".join(
            f"- {n.get('text', '')}" + (f" | doi:{n['doi']}" if n.get("doi") else "") +
            (f" | {n['url']}" if n.get("url") else "")
            for n in payload.get("source_notes", [])
        ),
        encoding="utf-8",
    )
    zip_path = out_dir / "carousel.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            zf.write(p, p.name)
        zf.write(caption_txt, "caption.txt")
        zf.write(sources_txt, "source_notes.txt")
    assets.append({
        "kind": "carousel_zip",
        "path": str(zip_path),
        "filename": "carousel.zip",
        "mime": "application/zip",
        "label": f"All {len(slides)} slides + caption + sources",
    })
    return assets


def render_static(payload: dict, out_dir: Path) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "static_post.png"
    render_static_post(payload, p)
    caption_txt = out_dir / "caption.txt"
    caption_txt.write_text(payload.get("caption", ""), encoding="utf-8")
    return [{
        "kind": "static_png",
        "path": str(p),
        "filename": "static_post.png",
        "mime": "image/png",
        "label": "1080 × 1080 static post",
    }, {
        "kind": "static_caption",
        "path": str(caption_txt),
        "filename": "caption.txt",
        "mime": "text/plain",
        "label": "Caption + source notes",
    }]


def _find_ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def render_reel(payload: dict, out_dir: Path) -> list[dict]:
    scenes = payload.get("scenes") or []
    if len(scenes) < 2:
        raise RenderError("Reel payload needs at least 2 scenes to render.")
    out_dir.mkdir(parents=True, exist_ok=True)

    frame_paths: list[Path] = []
    for i, scene in enumerate(scenes):
        p = out_dir / f"scene_{i:02d}.png"
        render_reel_scene(scene, payload, len(scenes), p)
        frame_paths.append(p)

    storyboard_txt = out_dir / "storyboard.txt"
    storyboard_txt.write_text(_storyboard_text(payload), encoding="utf-8")

    ffmpeg = _find_ffmpeg()
    ffmpeg_note = ""
    assets: list[dict] = [
        {
            "kind": "storyboard_scene",
            "path": str(frame_paths[0]),
            "filename": frame_paths[0].name,
            "mime": "image/png",
            "label": "Scene 1 (storyboard frame)",
        }
    ]

    if ffmpeg:
        mp4_path = out_dir / "reel.mp4"
        try:
            _assemble_mp4(ffmpeg, frame_paths, scenes, mp4_path, int(payload.get("duration_seconds", 45)))
            if mp4_path.exists() and mp4_path.stat().st_size > 1024:
                assets.insert(0, {
                    "kind": "reel_mp4",
                    "path": str(mp4_path),
                    "filename": "reel.mp4",
                    "mime": "video/mp4",
                    "label": f"Vertical MP4 ({payload.get('duration_seconds')}s, 1080×1920, captions on screen)",
                })
            else:
                ffmpeg = None
                ffmpeg_note = "video renderer produced no output"
        except Exception as exc:
            ffmpeg = None
            ffmpeg_note = f"video renderer unavailable ({str(exc)[:160]})"

    sb_zip = out_dir / "storyboard.zip"
    with zipfile.ZipFile(sb_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in frame_paths:
            zf.write(p, p.name)
        zf.write(storyboard_txt, "storyboard.txt")
        cap = out_dir / "caption.txt"
        cap.write_text(payload.get("caption", ""), encoding="utf-8")
        zf.write(cap, "caption.txt")

    label = (
        f"Storyboard frames + script ({ffmpeg_note})"
        if not ffmpeg
        else "Storyboard frames + script (backup)"
    )
    assets.append({
        "kind": "storyboard_zip",
        "path": str(sb_zip),
        "filename": "storyboard.zip",
        "mime": "application/zip",
        "label": label,
    })
    assets.append({
        "kind": "storyboard_script",
        "path": str(storyboard_txt),
        "filename": "storyboard.txt",
        "mime": "text/plain",
        "label": "Scene-by-scene script with timings",
    })
    return assets


def _assemble_mp4(ffmpeg: str, frames: list[Path], scenes: list[dict], out_path: Path, duration: int) -> None:
    list_path = out_path.parent / "frames.txt"
    lines = []
    for i, p in enumerate(frames):
        dur = float(scenes[i].get("end_seconds", 0)) - float(scenes[i].get("start_seconds", 0))
        dur = max(0.5, dur)
        lines.append(f"file '{p.as_posix()}'")
        lines.append(f"duration {dur:.3f}")
    lines.append(f"file '{frames[-1].as_posix()}'")
    list_path.write_text("\n".join(lines), encoding="utf-8")

    cmd = [
        ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-r", str(settings.reel_fps), "-pix_fmt", "yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0 or not out_path.exists():
        tail = (proc.stderr or "")[-800:]
        raise RenderError(f"ffmpeg failed to assemble the reel: {tail}")


def _storyboard_text(payload: dict) -> str:
    lines = [
        "STEER RESEARCH STUDIO — REEL STORYBOARD",
        "NOTE: This package contains storyboard frames and a full script.",
    ]
    mp4_note = "(generated alongside an MP4 when a video renderer is available)"
    lines.append(mp4_note)
    lines.append(f"Duration target: {payload.get('duration_seconds')}s | Scenes: {len(payload.get('scenes', []))}")
    lines.append("")
    lines.append(f"HOOK: {payload.get('hook', '')}")
    lines.append("")
    for sc in payload.get("scenes", []):
        lines.append(f"Scene {sc.get('index')}  [{sc.get('start_seconds')}s – {sc.get('end_seconds')}s]")
        lines.append(f"  ON-SCREEN: {sc.get('on_screen_text', '')}")
        lines.append(f"  VOICEOVER: {sc.get('voiceover', '')}")
        lines.append(f"  VISUAL:    {sc.get('visual_direction', '')}")
        if sc.get("claim_ids"):
            lines.append(f"  EVIDENCE:  {', '.join(sc['claim_ids'])}")
        lines.append("")
    lines.append("CAPTION:")
    lines.append(payload.get("caption", ""))
    lines.append("")
    lines.append("DISCLAIMER:")
    lines.append(payload.get("disclaimer", ""))
    return "\n".join(lines)


def render_version_assets(fmt: str, payload: dict, version_dir: Path) -> list[dict]:
    if fmt == "carousel":
        return render_carousel(payload, version_dir / "carousel")
    if fmt == "static":
        return render_static(payload, version_dir / "static")
    if fmt == "reel":
        return render_reel(payload, version_dir / "reel")
    if fmt == "deck":
        from app.services.rendering.pptx_builder import render_deck

        return render_deck(payload, version_dir / "deck")
    raise RenderError(f"Unknown deliverable format: {fmt}")
