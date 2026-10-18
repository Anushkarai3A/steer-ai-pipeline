from __future__ import annotations

"""Claim extraction stage.

Deterministic path: selects candidate claims as sentences that literally occur
in the extracted sources (results-oriented, quantitative statements first).
Every candidate therefore starts with a traceable location; the evidence stage
then confirms (or fails to confirm) the supporting passage.
"""

from app.core.text import extract_numbers, split_sentences
from app.models import EvidenceClaim, ResearchProject
from app.services.extraction.pdf_extractor import detect_sections

MAX_CLAIMS = 8
HIGH_RISK_TERMS = [
    "risk", "mortality", "death", "weight", "obesity", "diabetes", "cardiovascular",
    "stroke", "heart attack", "cancer", "dementia", "depression", "systolic",
    "blood pressure", "glucose", "insulin", "events", "hospitali",
]
EFFECT_RE = [
    "risk ratio", "hazard ratio", "odds ratio", "relative risk", "mean difference",
    "confidence interval", "p < 0.05", "p<0.05",
]


def extract_claims_deterministic(project: ResearchProject, summary: dict) -> list[dict]:
    candidates: list[dict] = []

    for item in summary.get("key_findings", []) or []:
        if item.get("text"):
            candidates.append({
                "claim_text": item["text"].strip(),
                "kind": "factual",
                "source_id": item.get("source_id"),
                "page": item.get("page"),
                "section": item.get("section"),
            })

    # supplement with numeric sentences from results sections if needed
    if len(candidates) < 4:
        for s in project.sources:
            if not s.document:
                continue
            for sec in detect_sections(s.document.pages):
                if sec["section"] not in {"results", "findings", "abstract", "body"}:
                    continue
                for sent in split_sentences(sec["text"]):
                    if not extract_numbers(sent):
                        continue
                    if any(c["claim_text"] == sent.strip() for c in candidates):
                        continue
                    candidates.append({
                        "claim_text": sent.strip(),
                        "kind": "factual",
                        "source_id": s.id,
                        "page": sec["page"],
                        "section": sec["section"],
                    })
                    if len(candidates) >= MAX_CLAIMS:
                        break
                if len(candidates) >= MAX_CLAIMS:
                    break
            if len(candidates) >= MAX_CLAIMS:
                break

    population_text = None
    for p in summary.get("population", []) or []:
        if p.get("text"):
            population_text = p["text"][:400]
            break
    design_text = None
    for d in summary.get("study_design", []) or []:
        if d.get("text"):
            design_text = d["text"][:400]
            break

    out = []
    for c in candidates[:MAX_CLAIMS]:
        text = c["claim_text"]
        low = text.lower()
        nums = extract_numbers(text)
        effect = next((p for p in EFFECT_RE if p in low), None)
        effect_size = None
        if effect and nums:
            idx = low.find(effect)
            effect_size = text[idx: idx + 90].strip()
        elif nums and "%" in text:
            effect_size = ", ".join(nums[:3])

        risk = "high" if any(t in low for t in HIGH_RISK_TERMS) else "medium"
        out.append({
            "claim_text": text,
            "kind": "factual",
            "risk_level": risk,
            "population": population_text,
            "study_design": design_text,
            "outcome": None,
            "effect_size": effect_size,
            "limitations": _first_limitation(summary),
            "candidate_source_id": c.get("source_id"),
            "candidate_page": c.get("page"),
            "candidate_section": c.get("section"),
            "extraction_method": "verbatim_sentence",
        })
    return out


def _first_limitation(summary: dict) -> str | None:
    for lim in summary.get("limitations", []) or []:
        if lim.get("text"):
            return lim["text"][:400]
    return None
