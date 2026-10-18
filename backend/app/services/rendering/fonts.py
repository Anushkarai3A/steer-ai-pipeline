from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from app.core.config import TEMPLATES_DIR

DESIGN_PATH = TEMPLATES_DIR / "design-system.json"

_WINDOWS_FONTS = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
_FONT_DIRS = [
    _WINDOWS_FONTS,
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/TTF"),
    Path("/System/Library/Fonts"),
    Path("/Library/Fonts"),
    Path.home() / "Library/Fonts",
]


@lru_cache
def design_tokens() -> dict:
    return json.loads(DESIGN_PATH.read_text(encoding="utf-8"))


@lru_cache
def resolve_font_path(candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        for d in _FONT_DIRS:
            p = d / name
            if p.exists():
                return str(p)
    return None


@lru_cache
def font(role: str, size: int) -> ImageFont.FreeTypeFont:
    """role: display | body | bold"""
    tokens = design_tokens()["fonts"]
    key = {"display": "display_candidates", "body": "body_candidates", "bold": "bold_candidates"}[role]
    path = resolve_font_path(tuple(tokens[key]))
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def text_width(draw, text: str, fnt) -> float:
    return draw.textlength(text, font=fnt)


def wrap_text(draw, text: str, fnt, max_width: int) -> list[str]:
    lines: list[str] = []
    for raw in str(text).split("\n"):
        words = raw.split()
        if not words:
            lines.append("")
            continue
        line = words[0]
        for w in words[1:]:
            trial = f"{line} {w}"
            if text_width(draw, trial, fnt) <= max_width:
                line = trial
            else:
                lines.append(line)
                line = w
        lines.append(line)
    return lines


def wrap_to_lines(draw, text: str, fnt, max_width: int, max_lines: int | None = None) -> list[str]:
    """Wrap `text` to `max_width`, truncating with an ellipsis only as a last resort.

    Callers that must keep the full text should use layout.fit_headline, which
    shrinks the font instead. This function is only a final safety net so a
    rendered line never exceeds `max_width`.
    """
    lines = wrap_text(draw, text, fnt, max_width)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        ell = "…"
        while lines[-1] and text_width(draw, lines[-1] + ell, fnt) > max_width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += ell
    return lines


def is_complete(text: str, lines: list[str]) -> bool:
    """True when the wrapped lines carry the whole text with no ellipsis."""
    if not lines or not text:
        return False
    if lines[-1].endswith("…") or lines[-1].endswith("..."):
        return False
    joined = " ".join(l for l in lines if l)
    return joined == text
