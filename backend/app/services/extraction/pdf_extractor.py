from __future__ import annotations

import re
from pathlib import Path

import fitz  # PyMuPDF

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>]+)\b")
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

SECTION_HEADINGS = [
    "abstract", "introduction", "background", "methods", "methodology", "materials and methods",
    "results", "findings", "discussion", "conclusion", "conclusions", "limitations", "references",
]


class ExtractionError(Exception):
    """Raised when a PDF cannot be converted into usable text."""


def extract_pdf(path: str | Path) -> dict:
    """Extract text with preserved page boundaries.

    Returns a dict: pages, full_text, page_count, method, metadata, warnings.
    Raises ExtractionError with a human-readable message on failure.
    """
    path = Path(path)
    if not path.exists():
        raise ExtractionError("Stored file is missing from disk.")
    if path.stat().st_size == 0:
        raise ExtractionError("File is empty (0 bytes).")

    try:
        doc = fitz.open(str(path))
    except Exception as exc:  # corrupt / not a PDF
        raise ExtractionError(f"File could not be opened as a PDF: {exc}") from exc

    try:
        if doc.page_count == 0:
            raise ExtractionError("PDF contains no pages.")

        raw_meta = doc.metadata or {}
        pages: list[dict] = []
        image_heavy_pages = 0
        for i in range(doc.page_count):
            page = doc.load_page(i)
            text = page.get_text("text") or ""
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            images = len(page.get_images(full=True))
            if len(text) < 40 and images > 0:
                image_heavy_pages += 1
            pages.append({"page": i + 1, "text": text})

        total_chars = sum(len(p["text"]) for p in pages)

        if image_heavy_pages and total_chars < 80:
            raise ExtractionError(
                "No extractable text found — this appears to be a scanned PDF. "
                "OCR is not configured in this environment; please upload a text-based PDF."
            )
        if total_chars < 20:
            raise ExtractionError("PDF contains no extractable text.")

        full_text = "\n\n".join(p["text"] for p in pages)
        metadata = {
            "pdf_title": (raw_meta.get("title") or "").strip() or None,
            "pdf_author": (raw_meta.get("author") or "").strip() or None,
            "pdf_creation_date": (raw_meta.get("creationDate") or "").strip() or None,
            "doi": _find_doi(full_text),
            "year": _find_year(raw_meta, full_text),
        }
        warnings: list[str] = []
        if image_heavy_pages:
            warnings.append(
                f"{image_heavy_pages} page(s) appear image-based; their text may be incomplete."
            )
        return {
            "pages": pages,
            "full_text": full_text,
            "page_count": doc.page_count,
            "method": "pymupdf",
            "metadata": metadata,
            "warnings": warnings,
        }
    finally:
        doc.close()


def _find_doi(text: str) -> str | None:
    m = DOI_RE.search(text[:20000])
    if m:
        doi = m.group(1).rstrip(".,;:)")
        return doi
    return None


def _find_year(meta: dict, text: str) -> int | None:
    for key in ("creationDate", "modDate"):
        v = meta.get(key) or ""
        m = re.search(r"D:(\d{4})", v)
        if m:
            return int(m.group(1))
    head = text[:3000]
    years = [int(y.group(0)) for y in YEAR_RE.finditer(head) if 1900 <= int(y.group(0)) <= 2030]
    if years:
        return years[0]
    return None


def detect_sections(pages: list[dict]) -> list[dict]:
    """Split pages into coarse sections using common paper headings.

    Returns [{"section": str, "page": int, "text": str}].
    """
    out: list[dict] = []
    current = "body"
    buffer: list[str] = []
    current_page = 1

    def flush() -> None:
        if buffer:
            out.append({"section": current, "page": current_page, "text": "\n".join(buffer).strip()})

    for p in pages:
        lines = p["text"].split("\n")
        for line in lines:
            stripped = line.strip().lower().rstrip(":")
            if stripped in SECTION_HEADINGS and len(line.strip()) < 40:
                flush()
                buffer = []
                current = stripped
                current_page = p["page"]
                continue
            buffer.append(line)
        buffer.append("")  # page break marker
    flush()
    return [s for s in out if s["text"].strip()]
