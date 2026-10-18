from __future__ import annotations

"""Reference normalisation for generated deliverables.

The PDF extractor sometimes stores a placeholder title ("untitled") or drops the
title entirely, and authors are stored as a JSON-encoded string on the source
row. Left alone this produced reference bullets that read "untitled, Public
Health Nutrition, 2017" or rendered as empty strings. This module turns any of
the real source shapes into a safe, complete reference string — never "null",
never "[object Object]", never a blank bullet.

Rules: never invent authors, titles, dates or DOIs. Show what is known. If
nothing usable is known, say so explicitly.
"""

import json
import re

MISSING_REFERENCE_TEXT = "Source details unavailable — verification required."

_PLACEHOLDER_TITLES = {
    "untitled",
    "untitled document",
    "untitled paper",
    "untitled article",
    "no title",
    "document",
    "paper",
    "article",
    "unknown",
    "none",
    "null",
    "",
}

# Matches a running header / footer the extractor sometimes lifts into the text.
_RUNNING_HEADER_RE = re.compile(
    r"^PLOS\s*(One)?\s*\|\s*https?://\S+.*$|^https?://\S+\s*(November|October|September|"
    r"August|July|June|May|April|March|February|January)\s+\d{1,2},\s+\d{4}.*$|"
    r"^[A-Z][a-z]+ \d{1,2}, \d{4}\s+\d+\s*/\s*\d+$",
    re.I,
)


def is_running_header(text: str) -> bool:
    """True when the text looks like a journal running header, not a sentence."""
    t = " ".join(str(text or "").split())
    if not t:
        return False
    if _RUNNING_HEADER_RE.match(t):
        return True
    # e.g. "PLOS One | https://doi.org/... November 18, 2025 2 / 12"
    if "|" in t and ("http" in t.lower() or "doi.org" in t.lower()):
        return True
    if re.match(r"^.{0,40}\d+\s*/\s*\d+\s*$", t) and ("|" in t or "http" in t.lower()):
        return True
    return False


def clean_title(raw) -> str | None:
    """Return a usable title, or None when the value is a placeholder/empty."""
    if raw is None:
        return None
    t = " ".join(str(raw).split()).strip().rstrip(".")
    if t.lower() in _PLACEHOLDER_TITLES:
        return None
    if len(t) < 8:
        return None
    return t


def parse_authors(raw) -> list[str]:
    """Authors may be a JSON string, a list, or None. Never raise."""
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        s = str(raw).strip()
        if not s or s.lower() in {"null", "none", "[]"}:
            return []
        try:
            parsed = json.loads(s)
            items = parsed if isinstance(parsed, list) else [parsed]
        except Exception:
            items = [p.strip() for p in re.split(r"[;,]| and ", s) if p.strip()]
    out: list[str] = []
    for it in items:
        name = " ".join(str(it).split()).strip()
        if name and name.lower() not in {"null", "none", "unknown", "n/a"}:
            out.append(name)
    return out


def format_authors(raw, max_authors: int = 3) -> str | None:
    names = parse_authors(raw)
    if not names:
        return None
    if len(names) <= max_authors:
        return ", ".join(names)
    return ", ".join(names[:max_authors]) + " et al."


def normalize_reference(source: dict | None) -> dict | None:
    """Turn a raw source dict into a safe reference. None when nothing usable."""
    if not source or not isinstance(source, dict):
        return None

    title = clean_title(source.get("title"))
    authors = format_authors(source.get("authors"))
    journal = " ".join(str(source.get("journal") or "").split()).strip() or None
    if journal and journal.lower() in _PLACEHOLDER_TITLES:
        journal = None
    year_raw = source.get("year")
    year = str(int(year_raw)) if isinstance(year_raw, (int, float)) and 1500 <= int(year_raw) <= 2100 else None
    if year is None and year_raw:
        m = re.search(r"\b(19|20)\d{2}\b", str(year_raw))
        year = m.group(0) if m else None
    doi = " ".join(str(source.get("doi") or "").split()).strip().lstrip("doi:").strip() or None
    if doi and doi.lower() in {"null", "none", "n/a", "-"}:
        doi = None
    url = " ".join(str(source.get("url") or source.get("canonical_url") or "").split()).strip() or None
    if url and url.lower() in {"null", "none", "n/a", "-"}:
        url = None
    if not url and doi:
        url = f"https://doi.org/{doi}"

    if not any([title, authors, journal, year, doi, url]):
        return None
    if not title and doi:
        # A real DOI is a verifiable locator. Using it as the title keeps the
        # reference from collapsing to "Authors, Journal, Year" with nothing to
        # identify the paper — and invents no bibliographic detail. The DOI
        # already appears as the title, so it is not repeated in the tail.
        title = f"doi:{doi}"

    return {
        "title": title,
        "authors": authors,
        "journal": journal,
        "year": year,
        "doi": doi,
        "url": url,
    }


def reference_line(ref: dict, *, with_url: bool = False) -> str:
    """One readable reference line from a normalised reference dict."""
    parts: list[str] = []
    if ref.get("authors"):
        parts.append(ref["authors"])
    if ref.get("title"):
        parts.append(ref["title"])
    tail: list[str] = []
    if ref.get("journal"):
        tail.append(ref["journal"])
    if ref.get("year"):
        tail.append(str(ref["year"]))
    if tail:
        parts.append(", ".join(tail))
    line = ". ".join(p for p in parts if p)
    # "et al." already ends in a period; joining with ". " yields "et al.."
    line = re.sub(r"\.\.(?=\s|$)", ".", line)
    line = re.sub(r"\.\s+\.", ".", line)
    if ref.get("doi") and f"doi:{ref['doi']}" != ref.get("title"):
        line += (f" — doi:{ref['doi']}" if line else f"doi:{ref['doi']}")
    elif with_url and ref.get("url") and ref.get("url") != ref.get("title"):
        line += (f" — {ref['url']}" if line else ref["url"])
    return line.strip(" .—")


def normalize_references(sources: list[dict] | None) -> list[dict]:
    """Normalise a list of raw source dicts, dropping unusable entries."""
    out: list[dict] = []
    seen: set[str] = set()
    for s in sources or []:
        ref = normalize_reference(s)
        if not ref:
            continue
        key = ref.get("doi") or ref.get("url") or ref.get("title") or ""
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def references_payload(sources: list[dict] | None) -> list[dict]:
    """References for a payload, with the honest fallback when none are usable."""
    refs = normalize_references(sources)
    if refs:
        return refs
    return [{
        "title": None,
        "authors": None,
        "journal": None,
        "year": None,
        "doi": None,
        "url": None,
        "note": MISSING_REFERENCE_TEXT,
    }]


def references_bullets(sources: list[dict] | None) -> list[str]:
    """Bullets for a PowerPoint references slide. Never empty, never blank."""
    refs = normalize_references(sources)
    if not refs:
        return [MISSING_REFERENCE_TEXT]
    return [reference_line(r) for r in refs]
