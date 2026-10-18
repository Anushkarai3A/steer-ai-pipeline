from __future__ import annotations

"""Evidence linking / verification stage.

Extraction of a claim and verification of its evidence are deliberately
separate steps. This module performs the verification half: it *retrieves*
supporting passages from stored extracted documents and attaches them as
ClaimEvidence rows. It never generates quotations — excerpts are literal
sentences from stored source text, with real page numbers.

Status policy:
  * verbatim passage with matching numbers        -> supported
  * overlapping passage, wording differs          -> partially_supported
  * overlapping passage, numbers do not match     -> needs_human_review
  * opposite-polarity passage found elsewhere     -> conflicting
  * nothing located                               -> needs_human_review
  * high-risk claim matching all of the above     -> never auto-supported;
    a doctor must verify even when a verbatim passage exists.
"""

from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.core.text import extract_numbers, has_negation, normalize, split_sentences, token_overlap
from app.models import ClaimEvidence, EvidenceClaim, ResearchProject
from app.services.extraction.pdf_extractor import detect_sections

OVERLAP_THRESHOLD = 0.55
CONTRADICTION_THRESHOLD = 0.60
#: Cap on supporting passages persisted per claim. Keeps the Evidence Lab list
#: readable while still surfacing more than the single best hit.
MAX_PERSISTED_PASSAGES = 4
LIMITATION_KEYWORDS = ["limitation", "however", "caution", "generaliz", "bias", "cannot", "uncertain"]


def _iter_sentences(project: ResearchProject):
    for source in project.sources:
        if not source.document:
            continue
        for sec in detect_sections(source.document.pages):
            for sent in split_sentences(sec["text"]):
                if len(sent) < 30:
                    continue
                yield source, sec["page"], sec["section"], sent


def _number_match(claim: str, passage: str) -> bool:
    claim_nums = extract_numbers(claim)
    if not claim_nums:
        return True
    passage_norm = passage.replace(" ", "")
    return all(n in passage_norm for n in claim_nums)


#: Score below which a passage is treated as background/methods boilerplate that
#: merely shares generic wording with the claim rather than restating it. Generic
#: tables, "p = 0.05" method sentences and literature reviews all land here.
#: Measured on the sample papers: a genuine restatement of a claim scores >= 0.70
#: in its own source, and the highest-scoring boilerplate match tops out around
#: 0.66, so this cutoff cleanly separates the two.
MIN_GENUINE_SCORE = 0.65


def locate_support(
    project: ResearchProject,
    claim_text: str,
    preferred_source_id: str | None = None,
) -> list[dict]:
    """Return candidate supporting passages, best first.

    A claim is normally copied verbatim out of one specific source, so the
    sentence is looked for in that source first; scanning every source for a
    similar sentence produced false matches (e.g. an unrelated paper's
    "Table 2 Baseline characteristics ... p = 0.05" method sentence being
    attached as support for a baseline-glucose claim). Cross-source candidates
    are still returned, but only after genuine in-source ones, and only when
    they look like a real restatement rather than shared boilerplate.
    """
    results = []
    for source, page, section, sent in _iter_sentences(project):
        exact = normalize(sent) == normalize(claim_text)
        score = 1.0 if exact else token_overlap(claim_text, sent)
        if exact:
            pass
        elif score < OVERLAP_THRESHOLD:
            continue
        elif not _number_match(claim_text, sent):
            # A passage whose numbers contradict or omit the claim's numbers is
            # not evidence for it, whatever the wording overlap.
            continue
        else:
            # Wording-overlap candidates are only evidence when they read as a
            # restatement. Generic method/table sentences score mid-range and
            # must not be attached as support.
            if score < MIN_GENUINE_SCORE:
                continue
        results.append({
            "source": source, "page": page, "section": section, "excerpt": sent,
            "score": score, "numbers_ok": _number_match(claim_text, sent), "exact": exact,
        })

    # Prefer the claim's own source (a sentence copied from a paper is genuine
    # evidence there); keep genuine cross-source matches as supporting context.
    def _rank(r: dict) -> tuple:
        same_source = 0 if (preferred_source_id and r["source"].id == preferred_source_id) else 1
        return (0 if r["exact"] else 1, same_source, -r["score"])

    results.sort(key=_rank)
    return results


def locate_contradiction(project: ResearchProject, claim_text: str, exclude_source_id: str) -> dict | None:
    claim_polarity = has_negation(claim_text)
    claim_nums = extract_numbers(claim_text)
    for source, page, section, sent in _iter_sentences(project):
        if source.id == exclude_source_id:
            continue
        score = token_overlap(claim_text, sent)
        if score < CONTRADICTION_THRESHOLD:
            continue
        if has_negation(sent) == claim_polarity:
            continue
        if claim_nums and not _number_match(claim_text, sent):
            continue
        return {"source": source, "page": page, "section": section, "excerpt": sent, "score": score}
    return None


def _page_limitation(project: ResearchProject, source_id: str, page: int | None) -> str | None:
    if page is None:
        return None
    for s in project.sources:
        if s.id != source_id or not s.document:
            continue
        for p in s.document.pages:
            if p["page"] != page:
                continue
            for sent in split_sentences(p["text"]):
                low = sent.lower()
                if any(k in low for k in LIMITATION_KEYWORDS) and len(sent) < 350:
                    return sent
    return None


def _linked_passages(claim: EvidenceClaim) -> list[ClaimEvidence]:
    """Persisted supporting passages that carry a real excerpt, in stored order."""
    return [
        e for e in claim.evidence
        if e.relation == "supports" and (e.excerpt or "").strip()
    ]


def verify_claim(
    db: Session,
    project: ResearchProject,
    claim: EvidenceClaim,
    preferred_source_id: str | None = None,
) -> EvidenceClaim:
    """Locate evidence for one persisted claim and set its status accordingly."""
    for ev in list(claim.evidence):
        db.delete(ev)
    db.flush()

    supports = locate_support(project, claim.claim_text, preferred_source_id=preferred_source_id)
    best = supports[0] if supports else None
    notes: list[str] = []

    if best is None:
        status = "needs_human_review"
        notes.append(
            "No supporting passage could be located in the extracted sources. "
            "Marked for human review — do not publish without checking."
        )
    elif not best["numbers_ok"]:
        status = "needs_human_review"
        notes.append(
            "A similar passage was found but numeric values in the claim do not appear in it. "
            "Verify the numbers manually."
        )
    elif best["exact"]:
        status = "supported"
        notes.append(
            f"Verbatim passage located in source {best['source'].id} on page {best['page']}"
            + (f" ({best['section']})" if best["section"] else "") + "."
        )
    else:
        status = "partially_supported"
        notes.append(
            f"Passage with {best['score']:.0%} wording overlap located on page {best['page']}; "
            "wording differs from the claim — verify it states the same thing."
        )

    if best is not None:
        limit = _page_limitation(project, best["source"].id, best["page"])
        if limit and not claim.limitations:
            claim.limitations = limit
        # Store every genuine candidate, best first. The claim's own source is
        # ranked first by locate_support, so the UI shows the passage the claim
        # was actually copied from; genuinely similar cross-source passages are
        # kept as additional supporting context (never as a substitute).
        for cand in supports[:MAX_PERSISTED_PASSAGES]:
            claim.evidence.append(
                ClaimEvidence(
                    id=new_id("evd"),
                    claim_id=claim.id,
                    source_id=cand["source"].id,
                    relation="supports",
                    excerpt=cand["excerpt"],
                    page=cand["page"],
                    section=cand["section"],
                    doi=cand["source"].doi,
                    url=cand["source"].canonical_url,
                    locator_method="verbatim_match" if cand["exact"] else "retrieval_overlap",
                )
            )
        contradiction = locate_contradiction(project, claim.claim_text, best["source"].id)
        if contradiction is not None:
            status = "conflicting"
            notes.append(
                f"Source {contradiction['source'].id} (page {contradiction['page']}) contains a "
                "highly similar passage with opposite polarity — sources disagree; surfacing both."
            )
            claim.evidence.append(
                ClaimEvidence(
                    id=new_id("evd"),
                    claim_id=claim.id,
                    source_id=contradiction["source"].id,
                    relation="contradicts",
                    excerpt=contradiction["excerpt"],
                    page=contradiction["page"],
                    section=contradiction["section"],
                    doi=contradiction["source"].doi,
                    url=contradiction["source"].canonical_url,
                    locator_method="retrieval_overlap",
                )
            )

    if status == "supported" and claim.risk_level == "high":
        status = "needs_human_review"
        notes.append(
            f"An exact verbatim passage was located on page {best['page']}, but high-risk "
            "claims are never auto-marked supported — a doctor must verify this claim "
            "before it can be treated as supported."
        )

    claim.status = status
    claim.verification_notes = " ".join(notes)
    db.flush()
    return claim


def supporting_evidence_count(claim: EvidenceClaim) -> int:
    """Number of persisted 'supports' passages with a real excerpt."""
    return sum(1 for e in claim.evidence if e.relation == "supports" and (e.excerpt or "").strip())


def reconcile_claim(db: Session, claim: EvidenceClaim) -> bool:
    """Bring a claim's status/notes back in line with persisted evidence.

    A claim marked 'supported' or 'partially_supported' without a single
    persisted supporting passage has been stranded (e.g. its evidence rows
    disappeared with a deleted source). Never fabricate a passage — demote
    the claim to human review and replace any note that references the
    now-missing evidence. Returns True when the claim was changed.
    """
    if claim.status not in {"supported", "partially_supported"}:
        return False
    has_support = (
        db.query(ClaimEvidence.id)
        .filter(
            ClaimEvidence.claim_id == claim.id,
            ClaimEvidence.relation == "supports",
            ClaimEvidence.excerpt != "",
        )
        .first()
        is not None
    )
    if has_support:
        return False
    old_status = claim.status
    old_notes = (claim.verification_notes or "").strip()
    claim.status = "needs_human_review"
    demotion_note = (
        f"Evidence records for this claim are missing (source removed or re-verification "
        f"pending). The previous '{old_status}' status and its verification note could not "
        "be confirmed against persisted evidence — status reset to 'needs human review'. "
        "Re-run evidence linking or verify manually."
    )
    # Never keep a note that still points at a page/passage which is no longer
    # persisted; if the existing note is already honest and generic, keep it.
    if "page" in old_notes.lower() or "located" in old_notes.lower() or not old_notes:
        claim.verification_notes = demotion_note
    db.flush()
    return True


def repair_stranded_claims(db: Session) -> list[str]:
    """One-shot reconciliation of claims stranded by the old source-deletion cascade.

    Historically, deleting a source cascade-deleted its claim_evidence rows at
    the database level while the evidence_claims rows (status, notes) survived,
    leaving 'supported' claims with zero passages. This demotes them back to
    human review and re-runs validation for affected projects.
    """
    candidates = (
        db.query(EvidenceClaim)
        .filter(EvidenceClaim.status.in_(("supported", "partially_supported")))
        .all()
    )
    changed: list[str] = []
    affected_projects: set[str] = set()
    for claim in candidates:
        if reconcile_claim(db, claim):
            changed.append(claim.id)
            affected_projects.add(claim.project_id)
    if not changed:
        return []
    db.commit()
    from app.services.review.workflow import revalidate_project

    for pid in sorted(affected_projects):
        project = db.get(ResearchProject, pid)
        if project is not None:
            revalidate_project(db, project)
    return changed
