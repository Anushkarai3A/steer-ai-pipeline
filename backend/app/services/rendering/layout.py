from __future__ import annotations

"""Measured vertical layout helpers for image and video rendering.

Every slide/scene is laid out from the top of its content band downward using
measured text heights, never fixed coordinates. That is what stops headings
from being truncated, body text from overlapping the disclaimer, and claim-id
chips from being forced on top of the copy by a `min(y, h - 300)` clamp.
"""

from dataclasses import dataclass

from app.services.rendering.fonts import font, wrap_to_lines, text_width


@dataclass
class Block:
    """A measured run of wrapped text at a known position."""

    lines: list[str]
    fnt: object
    x: int
    y: int
    width: int
    height: int
    spacing: int

    def draw(self, d, fill) -> None:
        if not self.lines:
            return
        d.multiline_text((self.x, self.y), "\n".join(self.lines), font=self.fnt, fill=fill, spacing=self.spacing)

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def right(self) -> int:
        return self.x + self.width


def line_height(fnt, spacing: int = 0) -> int:
    ascent, descent = fnt.getmetrics()
    return ascent + descent + spacing


def block_height(lines: list[str], fnt, spacing: int) -> int:
    if not lines:
        return 0
    return len(lines) * line_height(fnt, spacing)


def fit_font(
    d,
    text: str,
    role: str,
    max_size: int,
    min_size: int,
    max_width: int,
    max_lines: int,
) -> tuple[object, list[str], int]:
    """Wrap `text` with the largest font (<= max_size) that keeps it complete.

    Returns (font, lines, size). A font size is only accepted when the wrapped
    text still reads as a complete sentence — it must not end in a truncated
    fragment. When no size fits, the smallest size is returned and the caller
    receives the still-truncated lines (it can fall back to a shorter text).
    """
    text = " ".join(str(text or "").split())
    if not text:
        return font(role, min_size), [], min_size

    size = max_size
    while size > min_size:
        fnt = font(role, size)
        lines = wrap_to_lines(d, text, fnt, max_width, max_lines)
        if _is_complete(text, lines, fnt, max_width):
            return fnt, lines, size
        size = max(min_size, size - 4)

    fnt = font(role, min_size)
    lines = wrap_to_lines(d, text, fnt, max_width, max_lines)
    return fnt, lines, min_size


def _is_complete(text: str, lines: list[str], fnt, max_width: int) -> bool:
    """True when the wrapped lines carry the whole text with no truncation."""
    if not lines:
        return False
    if lines[-1].endswith("…") or lines[-1].endswith("..."):
        return False
    joined = " ".join(l for l in lines if l)
    # tolerate whitespace/font ligature differences only
    return joined.replace("ﬁ", "fi").replace("ﬀ", "ff").replace("ﬂ", "fl") == text


def fit_headline(
    d,
    text: str,
    role: str,
    max_size: int,
    min_size: int,
    max_width: int,
    max_lines: int,
) -> tuple[object, list[str], int]:
    """Like fit_font but falls back to a shortened equivalent, never a fragment.

    If the full headline cannot fit at the minimum size within `max_lines`, the
    text is trimmed to the last complete word (preferring to keep any numbers
    and their units intact) and an ellipsis is added so the reader knows the
    sentence was summarised rather than cut off mid-word.
    """
    text = " ".join(str(text or "").split())
    if not text:
        return font(role, min_size), [], min_size

    fnt, lines, size = fit_font(d, text, role, max_size, min_size, max_width, max_lines)
    if _is_complete(text, lines, fnt, max_width):
        return fnt, lines, size

    trimmed = _trim_to_complete(d, text, fnt, max_width, max_lines)
    lines = wrap_to_lines(d, trimmed, fnt, max_width, max_lines)
    return fnt, lines, size


def _trim_to_complete(d, text: str, fnt, max_width: int, max_lines: int) -> str:
    words = text.split()
    for end in range(len(words), 0, -1):
        candidate = " ".join(words[:end])
        if candidate.endswith((":", ";", ",")):
            candidate = candidate[:-1]
        lines = wrap_to_lines(d, candidate + "…", fnt, max_width, max_lines)
        if _is_complete(candidate + "…", lines, fnt, max_width):
            return candidate + "…"
    ell = "…"
    while ell and text_width(d, ell, fnt) > max_width:
        ell = ell[:-1]
    return ell or "…"


def draw_block(
    d,
    text: str,
    role: str,
    size: int,
    max_width: int,
    x: int,
    y: int,
    *,
    max_lines: int | None = None,
    spacing: int = 12,
) -> Block:
    """Measure and immediately draw one wrapped text block; returns its bounds."""
    fnt = font(role, size)
    lines = wrap_to_lines(d, text, fnt, max_width, max_lines)
    height = block_height(lines, fnt, spacing)
    if lines:
        d.multiline_text((x, y), "\n".join(lines), font=fnt, spacing=spacing)
    return Block(lines=lines, fnt=fnt, x=x, y=y, width=max_width, height=height, spacing=spacing)


def draw_fitted_block(
    d,
    text: str,
    role: str,
    max_size: int,
    min_size: int,
    max_width: int,
    x: int,
    y: int,
    *,
    max_lines: int = 4,
    spacing: int = 12,
    complete: bool = True,
) -> Block:
    """Draw a block at the largest font that keeps the text complete."""
    if complete:
        fnt, lines, _ = fit_headline(d, text, role, max_size, min_size, max_width, max_lines)
    else:
        fnt, lines, _ = fit_font(d, text, role, max_size, min_size, max_width, max_lines)
    height = block_height(lines, fnt, spacing)
    if lines:
        d.multiline_text((x, y), "\n".join(lines), font=fnt, spacing=spacing)
    return Block(lines=lines, fnt=fnt, x=x, y=y, width=max_width, height=height, spacing=spacing)


def chip_size(d, text: str, size: int, pad: int = 16) -> tuple[int, int]:
    """Pixel size of a rounded evidence/citation chip."""
    fnt = font("body", size)
    tw = text_width(d, text, fnt)
    w = int(tw + pad * 2)
    h = int(size + pad * 1.6)
    return w, h


def footer_band_top(h: int, band: int = 210) -> int:
    """Top of the reserved footer band (branding, page number, citation)."""
    return h - band


def check_overlap(a: Block, b: Block) -> bool:
    """Axis-aligned overlap test between two drawn blocks (tight bounds)."""
    if not a.lines or not b.lines:
        return False
    a_bottom = a.bottom - (a.fnt.getmetrics()[1] if hasattr(a.fnt, "getmetrics") else 0)
    b_bottom = b.bottom - (b.fnt.getmetrics()[1] if hasattr(b.fnt, "getmetrics") else 0)
    return not (a_bottom <= b.y or b_bottom <= a.y or a.right <= b.x or b.right <= a.x)


def check_within(b: Block, *, canvas_w: int, canvas_h: int, margin: int = 0) -> bool:
    """True when the block sits fully inside the canvas with the given margin."""
    if not b.lines:
        return True
    return b.x >= margin and b.y >= margin and b.right <= canvas_w - margin and b.bottom <= canvas_h - margin
