"""Fetch real open-access research papers for the demo experience.

Downloads three genuinely published, open-access papers (PLOS, Creative
Commons licensed) that form a coherent "sleep and cardiometabolic health"
sample project, stores them in samples/ and writes ATTRIBUTION.json with full
citation metadata so every sample is properly attributed.

Run:  python scripts/fetch_sample_sources.py
Safe to re-run. If the network is unavailable the script reports it clearly
and the app falls back to clearly-labelled synthetic DEMO DATA samples.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
SAMPLES = REPO / "samples"
HEADERS = {"User-Agent": "SteerResearchStudio/1.0 (demo sample fetcher; contact: demo@example.com)"}

# Three real, open-access papers (PLOS, CC-licensed) on one coherent theme.
SAMPLE_DOIS = [
    "10.1371/journal.pone.0337232",  # Sleep duration & CVD risk in type 2 diabetes (prospective cohort)
    "10.1371/journal.pone.0307120",  # Sleep duration & hypertension incidence (systematic review/meta-analysis)
    "10.1371/journal.pone.0330782",  # Mendelian randomization: sleep duration & type 2 diabetes
]


def safe_name(doi: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", doi).strip("_") + ".pdf"


def crossref(doi: str) -> dict | None:
    try:
        r = httpx.get(f"https://api.crossref.org/works/{doi}", timeout=30, headers=HEADERS)
        if r.status_code != 200:
            return None
        return r.json().get("message", {})
    except Exception:
        return None


def plos_pdf_url(doi: str) -> str | None:
    m = re.match(r"10\.1371/journal\.(.+)", doi)
    if not m:
        return None
    journal_slug = {
        "pone": "plosone",
        "pmed": "plosmedicine",
        "pbio": "plosbiology",
        "pgen": "plosgenetics",
        "ppat": "plospathogens",
    }.get(m.group(1).split(".")[0], "plosone")
    return f"https://journals.plos.org/{journal_slug}/article/file?id={doi}&type=printable"


def download(url: str) -> bytes | None:
    try:
        r = httpx.get(url, timeout=60, follow_redirects=True, headers=HEADERS)
        if r.status_code == 200 and r.content[:5] == b"%PDF-":
            return r.content
    except Exception:
        return None
    return None


def main() -> int:
    SAMPLES.mkdir(exist_ok=True)
    attribution: list[dict] = []
    failures: list[str] = []

    for doi in SAMPLE_DOIS:
        fname = safe_name(doi)
        path = SAMPLES / fname
        meta = crossref(doi)
        if meta is None:
            failures.append(f"{doi}: Crossref metadata unavailable (network?)")
            continue
        if path.exists() and path.stat().st_size > 1000:
            print(f"[skip] {fname} already present")
        else:
            url = plos_pdf_url(doi)
            data = download(url) if url else None
            if not data:
                failures.append(f"{doi}: PDF download failed")
                continue
            path.write_bytes(data)
            print(f"[ok] {fname} ({len(data)//1024} KB)")

        license_urls = [l.get("URL") for l in (meta.get("license") or [])]
        attribution.append({
            "file": fname,
            "title": (meta.get("title") or [None])[0],
            "authors": [
                " ".join(x for x in [a.get("given"), a.get("family")] if x)
                for a in (meta.get("author") or [])
            ],
            "journal": (meta.get("container-title") or [None])[0],
            "year": next(
                (p[0][0] for key in ("published-print", "published-online", "issued")
                 for p in [(meta.get(key) or {}).get("date-parts") or []] if p and p[0]),
                None,
            ),
            "doi": doi,
            "url": f"https://doi.org/{doi}",
            "license": license_urls,
            "source": "Public Library of Science (PLOS), open access",
            "download_url": plos_pdf_url(doi),
        })

    if attribution:
        (SAMPLES / "ATTRIBUTION.json").write_text(json.dumps(attribution, indent=2), encoding="utf-8")
        print(f"Wrote {len(attribution)} sample papers + ATTRIBUTION.json to {SAMPLES}")
    for f in failures:
        print(f"[fail] {f}")
    if len(attribution) < 2:
        print(
            "[error] Fewer than 2 open-access sample papers could be downloaded.\n"
            "The app will fall back to clearly-labelled synthetic DEMO DATA samples."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
