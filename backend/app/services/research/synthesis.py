from __future__ import annotations

"""Research synthesis stage.

Builds a structured, source-referenced summary of the uploaded material.
The deterministic path only reports sentences that literally exist in the
extracted documents (with page references); anything it cannot determine is
explicitly reported as unavailable instead of being invented.
"""

from sqlalchemy.orm import Session

from app.core.text import extract_numbers, split_sentences
from app.models import ExtractedDocument, ResearchProject, ResearchSource
from app.services.extraction.pdf_extractor import detect_sections

DESIGN_KEYWORDS = [
    "randomised", "randomized", "random assignment", "controlled trial", "cohort study",
    "cross-sectional", "case-control", "meta-analysis", "systematic review", "observational",
    "longitudinal", "placebo", "double-blind", "retrospective", "prospective",
]
POPULATION_KEYWORDS = [
    "participants", "patients", "adults", "children", "adolescents", "older adults",
    "pregnant", "women", "men", "aged ", "volunteers", "subjects", "sample of",
]
LIMITATION_KEYWORDS = [
    "limitation", "however", "caution", "generaliz", "generalis", "bias", "cannot",
    "not causal", "causality", "uncertain", "may not", "small sample", "short follow-up",
    "self-reported", "association only",
]
INTERPRETATION_KEYWORDS = ["suggest", "indicates", "indicate", "may ", "could ", "appears to", "is consistent with"]
CONFLICT_KEYWORDS = ["inconsistent", "contradict", "conflicts with", "differs from", "in contrast to", "disagree"]


def _entry(text: str, source: ResearchSource | None, page: int | None, category: str, section: str | None = None) -> dict:
    return {
        "text": text.strip(),
        "source_id": source.id if source else None,
        "page": page,
        "category": category,
        "section": section,
    }


def _source_map(db: Session, project: ResearchProject) -> dict[str, ResearchSource]:
    return {s.id: s for s in project.sources}


def synthesize_deterministic(db: Session, project: ResearchProject) -> dict:
    sources = [s for s in project.sources if s.document and s.document.full_text.strip()]
    src_map = _source_map(db, project)

    all_sections: list[tuple[ResearchSource, dict]] = []
    for s in sources:
        for sec in detect_sections(s.document.pages):
            all_sections.append((s, sec))

    def sentences_in(section_names: list[str] | None = None, source_ids: list[str] | None = None) -> list[tuple[ResearchSource, dict, str]]:
        out = []
        for source, sec in all_sections:
            if section_names and sec["section"] not in section_names:
                continue
            if source_ids and source.id not in source_ids:
                continue
            for sent in split_sentences(sec["text"]):
                out.append((source, sec, sent))
        return out

    research_question = "Not explicitly stated in the extracted sources."
    for _, sec, sent in sentences_in(["abstract", "introduction", "background"]):
        if "?" in sent:
            research_question = sent
            break
        if any(k in sent.lower() for k in ["we aimed", "we sought", "objective", "we investigated", "this study"]):
            research_question = sent
            break

    study_design = []
    for _, sec, sent in sentences_in(["methods", "methodology", "materials and methods", "abstract", "body"]):
        low = sent.lower()
        if any(k in low for k in DESIGN_KEYWORDS):
            study_design.append(_entry(sent, None, None, "background", sec["section"]))
        if len(study_design) >= 3:
            break
    # attach real source references for design sentences by re-searching per source
    study_design = _reanchor(db, project, study_design, ["methods", "abstract"])

    population = []
    for _, sec, sent in sentences_in(["methods", "abstract"]):
        if any(k in sent.lower() for k in POPULATION_KEYWORDS):
            population.append(_entry(sent, None, None, "background", sec["section"]))
        if len(population) >= 3:
            break
    population = _reanchor(db, project, population, ["methods", "abstract"])

    key_findings = []
    for source, sec, sent in sentences_in(["results", "findings", "abstract"]):
        nums = extract_numbers(sent)
        if nums and len(sent) < 400:
            key_findings.append(_entry(sent, source, sec["page"], "finding", sec["section"]))
        if len(key_findings) >= 8:
            break

    methods = []
    for source, sec, sent in sentences_in(["methods", "methodology", "materials and methods"]):
        if len(sent) < 300:
            methods.append(_entry(sent, source, sec["page"], "background", sec["section"]))
        if len(methods) >= 4:
            break

    limitations = []
    for source, sec, sent in sentences_in(None):
        if any(k in sent.lower() for k in LIMITATION_KEYWORDS):
            limitations.append(_entry(sent, source, sec["page"], "limitation", sec["section"]))
        if len(limitations) >= 6:
            break

    conflicts = []
    for source, sec, sent in sentences_in(None):
        if any(k in sent.lower() for k in CONFLICT_KEYWORDS):
            conflicts.append(_entry(sent, source, sec["page"], "conflict", sec["section"]))
        if len(conflicts) >= 4:
            break

    interpretation = []
    for source, sec, sent in sentences_in(["discussion", "conclusion", "conclusions"]):
        if any(k in sent.lower() for k in INTERPRETATION_KEYWORDS):
            interpretation.append(_entry(sent, source, sec["page"], "interpretation", sec["section"]))
        if len(interpretation) >= 4:
            break

    numbers = []
    for f in key_findings[:6]:
        nums = extract_numbers(f["text"])
        if nums:
            numbers.append({**f, "values": nums})

    not_established: list[dict] = []
    design_text = " ".join(d["text"].lower() for d in study_design)
    if any(k in design_text for k in ["cross-sectional", "observational", "cohort", "retrospective", "case-control"]):
        not_established.append(_entry(
            "The included study designs are observational; they can show associations but do not "
            "by themselves establish that one factor causes another.",
            None, None, "interpretation",
        ))
    if not sources:
        not_established.append(_entry(
            "No sources have been successfully extracted, so nothing can be established yet.",
            None, None, "interpretation",
        ))
    not_established.append(_entry(
        "Absence of a detected conflict between sources does not mean the sources agree — "
        "disagreement detection here only finds explicit statements in the extracted text.",
        None, None, "interpretation",
    ))

    if conflicts:
        conflict_note = "Explicit conflicting statements were found in the extracted text (listed above)."
    else:
        conflict_note = (
            "No explicit disagreement was detected in the extracted text. This is not evidence of "
            "agreement — a human should compare the sources directly."
        )

    summary = {
        "mode": "deterministic",
        "mode_label": "Rule-based extraction from source text (no AI model used)",
        "research_question": research_question,
        "study_design": study_design,
        "population": population,
        "methods": methods,
        "key_findings": key_findings,
        "numbers": numbers,
        "limitations": limitations,
        "conflicts": conflicts,
        "conflict_note": conflict_note,
        "practical_interpretation": interpretation,
        "not_established": not_established,
        "sources": [
            {
                "id": s.id,
                "title": s.title,
                "year": s.year,
                "journal": s.journal,
                "doi": s.doi,
                "authors": s.authors,
                "status": s.status,
            }
            for s in project.sources
        ],
        "excluded_sources": [
            {"id": s.id, "title": s.title, "status": s.status, "error": s.error}
            for s in project.sources
            if not (s.document and s.document.full_text.strip())
        ],
    }
    return summary


def _reanchor(db: Session, project: ResearchProject, entries: list[dict], preferred_sections: list[str]) -> list[dict]:
    """Attach a real source + page to entries that were collected without one."""
    from app.core.text import token_overlap

    for entry in entries:
        if entry.get("source_id"):
            continue
        best = (None, 0.0)
        for s in project.sources:
            if not s.document:
                continue
            for page in s.document.pages:
                score = token_overlap(entry["text"], page["text"])
                if score > best[1]:
                    best = (s, score, page["page"])  # type: ignore[assignment]
        if best[0] and best[1] >= 0.55:
            entry["source_id"] = best[0].id
            entry["page"] = best[2]  # type: ignore[index]
    return entries


def persist_findings(db: Session, project: ResearchProject, summary: dict) -> int:
    from app.core.ids import new_id
    from app.models import ResearchFinding

    db.query(ResearchFinding).filter(ResearchFinding.project_id == project.id).delete()
    count = 0
    for bucket in ["study_design", "population", "methods", "key_findings", "limitations", "conflicts", "practical_interpretation"]:
        for item in summary.get(bucket, []) or []:
            if not item.get("text"):
                continue
            db.add(
                ResearchFinding(
                    id=new_id("fnd"),
                    project_id=project.id,
                    source_id=item.get("source_id"),
                    category=item.get("category", "finding"),
                    text=item["text"],
                    page=item.get("page"),
                    section=item.get("section"),
                )
            )
            count += 1
    return count
