from __future__ import annotations

"""Metadata enrichment for DOI / URL sources.

We only use public, paywall-respecting endpoints:
  * Crossref REST API for DOI metadata (title, authors, year, journal).
No full text is fetched from behind a paywall. Failures return None and the
field is shown as "unavailable" rather than invented.
"""

import httpx

TIMEOUT = 12.0
CROSSREF = "https://api.crossref.org/works/"


def crossref_lookup(doi: str) -> dict | None:
    try:
        resp = httpx.get(
            CROSSREF + doi,
            timeout=TIMEOUT,
            headers={"User-Agent": "SteerResearchStudio/1.0 (mailto:demo@example.com)"},
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        msg = resp.json().get("message", {})
    except Exception:
        return None

    title = (msg.get("title") or [None])[0]
    year = None
    for key in ("published-print", "published-online", "issued"):
        parts = (msg.get(key) or {}).get("date-parts") or []
        if parts and parts[0]:
            year = parts[0][0]
            break
    authors = []
    for a in msg.get("author", []) or []:
        name = " ".join(x for x in [a.get("given"), a.get("family")] if x)
        if name:
            authors.append(name)
    journal = (msg.get("container-title") or [None])[0]
    url = msg.get("URL")
    pdf_links = [
        l.get("URL")
        for l in (msg.get("link") or [])
        if (l.get("content-type") or "").lower() == "application/pdf"
    ]
    return {
        "doi": doi,
        "title": title,
        "authors": authors or None,
        "year": year,
        "journal": journal,
        "url": url,
        "pdf_url": pdf_links[0] if pdf_links else None,
    }


def fetch_public_pdf(url: str) -> bytes | None:
    """Fetch a PDF from a public URL. Returns None on any failure.

    Deliberately does not attempt to bypass paywalls or authentication.
    """
    try:
        resp = httpx.get(url, timeout=25.0, follow_redirects=True, headers={"User-Agent": "SteerResearchStudio/1.0"})
        if resp.status_code != 200:
            return None
        ctype = (resp.headers.get("content-type") or "").lower()
        if "pdf" not in ctype and not resp.content[:5].startswith(b"%PDF"):
            return None
        if len(resp.content) > 30 * 1024 * 1024:
            return None
        return resp.content
    except Exception:
        return None
