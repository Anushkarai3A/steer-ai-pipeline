from __future__ import annotations

"""Deterministic validation of generated content (Stage 6).

These checks run without a model so they always execute, even offline:
citation integrity, evidence status gates, caveat retention, fabricated
statistics/quotations, overstatement, fear/shame language, medication
promotion, personalized advice, causal overreach and population
generalization.

A validation pass is NOT a fact-check by a qualified clinician and never
substitutes for doctor approval — it only blocks silent failures.
"""

import re
from datetime import datetime, timezone

from app.core.text import extract_numbers, has_overclaim, normalize
from app.models import EvidenceClaim, ResearchProject

RULES_VERSION = "deterministic_rules_v1"

DISCLAIMER_REQUIRED_PHRASES = ["not medical advice"]
QUOTE_RE = re.compile(r"[\"“]([^\"“”]{15,200})[\"”]")

DRUG_RECOMMENDATION_RE = re.compile(
    r"\b((take|start|switch to|ask your doctor for|get a prescription for|use)\s+(the\s+)?"
    r"(ozempic|wegovy|mounjaro|metformin|semaglutide|atorvastatin|lisinopril|prozac|sertraline|insulin)\b)",
    re.I,
)
MED_CHANGE_RE = re.compile(
    r"\b((start|stop|increase|decrease|change|quit|cut)\s+(taking\s+)?(your\s+)?"
    r"(medication|medications|meds|dose|dosage|prescription|pills))\b",
    re.I,
)
PERSONAL_ADVICE_RE = re.compile(
    r"\b(you (should|must|need to) (take|start|stop|increase|decrease|cut|skip|double)\b|"
    r"your (own )?dosage|based on your diagnosis)\b",
    re.I,
)
DIAGNOSIS_RE = re.compile(r"\b(this means you have|you are (definitely )?(diagnosed|diabetic|hypertensive))\b", re.I)
FEAR_SHAME_RE = re.compile(
    r"\b(shame on you|your fault|disgusting|embarrassing|lazy|gross|stop being fat|"
    r"ruin your body|killing yourself|before it's too late|dangerous truth)\b",
    re.I,
)
GENERALIZATION_RE = re.compile(
    r"\b(everyone|all adults|anyone (in the world)|works for everyone|proven for all|"
    r"always works|guaranteed (to|results)|100\s*%)\b",
    re.I,
)
CAUSAL_RE = re.compile(
    r"\b(causes|caused by|prevents?|cuts|reduces\s+([a-z]+\s+)?risk|lowers\s+([a-z]+\s+)?risk|"
    r"protects against|leads to|will (reduce|lower|prevent))\b",
    re.I,
)
OBSERVATIONAL_RE = re.compile(
    r"(cross-sectional|observational|cohort|retrospective|case-control|correlat)", re.I
)
RISKY_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|percent)|\d+\.\d+|\d{2,}|\d+\s+in\s+\d+", re.I)

# Internal ids and DOIs are not statistics — mask them before number scanning.
_ID_MASK_RE = re.compile(
    r"\b(?:CLM-\d+|src_[A-Za-z0-9]+|dlv_[A-Za-z0-9]+|cv_[A-Za-z0-9]+|"
    r"ast_[A-Za-z0-9]+|prj_[A-Za-z0-9]+|run_[A-Za-z0-9]+)\b"
)
_DOI_MASK_RE = re.compile(r"\b10\.\d{4,9}/[^\s,;]+")


def _mask_ids(text: str) -> str:
    return _DOI_MASK_RE.sub(" ", _ID_MASK_RE.sub(" ", text))


def _iter_texts(fmt: str, payload: dict):
    """Yield (location, text, claim_ids) for every user-visible text piece."""
    if fmt == "carousel":
        for i, slide in enumerate(payload.get("slides", [])):
            yield f"slides[{i}].headline", slide.get("headline", ""), slide.get("claim_ids", [])
            yield f"slides[{i}].body", slide.get("body", ""), slide.get("claim_ids", [])
        yield "caption", payload.get("caption", ""), []
    elif fmt == "static":
        yield "headline", payload.get("headline", ""), payload.get("claim_ids", [])
        yield "body", payload.get("body", ""), payload.get("claim_ids", [])
        yield "caption", payload.get("caption", ""), []
    elif fmt == "reel":
        yield "hook", payload.get("hook", ""), []
        for i, scene in enumerate(payload.get("scenes", [])):
            yield f"scenes[{i}].on_screen_text", scene.get("on_screen_text", ""), scene.get("claim_ids", [])
            yield f"scenes[{i}].voiceover", scene.get("voiceover", ""), scene.get("claim_ids", [])
        yield "caption", payload.get("caption", ""), []
    elif fmt == "deck":
        yield "deck_title", payload.get("deck_title", ""), []
        yield "subtitle", payload.get("subtitle", ""), []
        for i, slide in enumerate(payload.get("slides", [])):
            claim_ids = slide.get("claim_ids", [])
            yield f"slides[{i}].title", slide.get("title", ""), claim_ids
            for j, b in enumerate(slide.get("bullets", []) or []):
                yield f"slides[{i}].bullets[{j}]", str(b), claim_ids
            table = slide.get("table") or {}
            for r, row in enumerate(table.get("rows") or []):
                for c, val in enumerate(row or []):
                    yield f"slides[{i}].table[{r}][{c}]", str(val), claim_ids


# Thousands separators and bare digits inside statistics. extract_numbers()
# splits on the comma ("1,360" -> "1" and "360"), so the allowed-number set
# must be built the same way or "1,360" reads as a fabricated "1".
_NUM_SCAN_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers_in(text: str) -> set[str]:
    out: set[str] = set()
    for m in _NUM_SCAN_RE.finditer(text or ""):
        tok = m.group(0).replace(" ", "")
        out.update(extract_numbers(tok))
        out.add(tok)
    return out


def _allowed_numbers(project: ResearchProject, claims: list[EvidenceClaim]) -> set[str]:
    allowed: set[str] = set()
    summary = project.summary or {}
    for bucket in ["key_findings", "numbers", "population", "methods", "study_design", "limitations", "practical_interpretation"]:
        for entry in summary.get(bucket, []) or []:
            allowed.update(_numbers_in(entry.get("text") or ""))
    for c in claims:
        allowed.update(_numbers_in(c.claim_text))
        allowed.update(_numbers_in(c.effect_size or ""))
        for ev in c.evidence:
            allowed.update(_numbers_in(ev.excerpt))
            if ev.page is not None:
                allowed.add(str(ev.page))
    for s in project.sources:
        if s.year:
            allowed.add(str(s.year))
        if s.page_count:
            allowed.add(str(s.page_count))
    return {a.replace(" ", "") for a in allowed}


def _linked_claim_defs(location: str, payload: dict) -> list[str]:
    if location.startswith("slides["):
        idx = int(location.split("[")[1].split("]")[0])
        slides = payload.get("slides", [])
        if idx < len(slides):
            return slides[idx].get("claim_ids", [])
    elif location.startswith("scenes["):
        idx = int(location.split("[")[1].split("]")[0])
        scenes = payload.get("scenes", [])
        if idx < len(scenes):
            return scenes[idx].get("claim_ids", [])
    elif location in {"headline", "body"}:
        return payload.get("claim_ids", [])
    return []


def validate_payload(
    fmt: str,
    payload: dict,
    project: ResearchProject,
    claims_by_id: dict[str, EvidenceClaim],
) -> dict:
    issues: list[dict] = []

    def add(rule: str, severity: str, message: str, location: str | None = None, claim_id: str | None = None) -> None:
        issues.append({
            "rule": rule,
            "severity": severity,
            "message": message,
            "claim_id": claim_id,
            "location": location,
        })

    allowed_numbers = _allowed_numbers(project, list(claims_by_id.values()))
    used_claim_ids: set[str] = set()

    for location, text, claim_ids in _iter_texts(fmt, payload):
        linked = claim_ids or _linked_claim_defs(location, payload)
        used_claim_ids.update(linked)

        # RULE: citations must point to existing evidence records
        for cid in linked:
            if cid not in claims_by_id:
                add("citation_integrity", "error",
                    f"Claim id {cid} does not exist in the evidence registry.", location, cid)

        # evidence status gates (RULE 2)
        for cid in linked:
            claim = claims_by_id.get(cid)
            if not claim:
                continue
            if claim.status == "unsupported":
                add("evidence_status", "error",
                    f"{cid} is marked UNSUPPORTED but is used as a factual statement.", location, cid)
            elif claim.status == "needs_human_review" and claim.risk_level == "high":
                add("evidence_status", "error",
                    f"{cid} is a high-risk claim still marked 'needs human review'.", location, cid)
            elif claim.status == "needs_human_review":
                add("evidence_status", "warning",
                    f"{cid} still needs human evidence review.", location, cid)
            elif claim.status == "conflicting":
                sev = "error" if claim.risk_level == "high" else "warning"
                add("evidence_status", sev,
                    f"{cid} has conflicting evidence across sources.", location, cid)
            elif claim.status == "partially_supported":
                add("evidence_status", "warning",
                    f"{cid} is only partially supported — verify wording.", location, cid)

            # RULE: a status is only meaningful if the evidence behind it is
            # actually persisted — a stranded 'supported' claim must not pass.
            if claim.status in {"supported", "partially_supported"} and not any(
                e.relation == "supports" and (e.excerpt or "").strip() for e in claim.evidence
            ):
                add("missing_evidence", "error",
                    f"{cid} is marked '{claim.status}' but has no persisted supporting "
                    "evidence passage — re-run evidence linking before publishing.",
                    location, cid)

        # numeric traceability (RULE: no fabricated statistics)
        scan = _mask_ids(text)
        risky = [m.group(0) for m in RISKY_NUMBER_RE.finditer(scan)]
        if risky and not linked and location != "caption":
            add("unlinked_numeric", "warning",
                f"Numeric statement '{risky[0].strip()}' appears without a linked claim id.", location)
        for num in risky:
            n = num.replace(" ", "")
            candidates = extract_numbers(n) or [n]
            if not any(c in allowed_numbers for c in candidates):
                add("fabricated_statistic", "error",
                    f"Numeric value '{num.strip()}' does not appear in linked evidence.", location)

        # fabricated quotations
        for q in QUOTE_RE.finditer(text):
            quoted = normalize(q.group(1))
            excerpts = " ".join(
                normalize(ev.excerpt)
                for cid in linked
                for ev in (claims_by_id[cid].evidence if cid in claims_by_id else [])
            )
            if quoted not in excerpts:
                add("fabricated_quotation", "error",
                    "Quoted text does not appear in the linked evidence excerpts.", location)

        # overstatement / miracle claims
        if has_overclaim(text):
            add("overstatement", "error",
                "Text contains guaranteed/miracle/proven language that overstates findings.", location)

        # fear / shame language
        if FEAR_SHAME_RE.search(text):
            add("fear_shame", "error",
                "Text uses fear-based or shaming language.", location)

        # drug promotion / medication instructions
        if DRUG_RECOMMENDATION_RE.search(text) or MED_CHANGE_RE.search(text):
            add("medication_advice", "error",
                "Text recommends starting/stopping/changing medication or promotes a specific drug.", location)

        # personalized medical advice / diagnosis
        if PERSONAL_ADVICE_RE.search(text) or DIAGNOSIS_RE.search(text):
            add("personalized_advice", "error",
                "Text gives personalized medical advice or diagnostic claims.", location)

        # generalization / universal claims
        if GENERALIZATION_RE.search(text):
            add("universal_claim", "error",
            "Text implies a universal or guaranteed outcome.", location)

        # causal language from observational evidence
        if CAUSAL_RE.search(text):
            for cid in linked:
                claim = claims_by_id.get(cid)
                if claim and claim.study_design and OBSERVATIONAL_RE.search(claim.study_design):
                    add("causal_overreach", "error",
                        f"Causal wording used with {cid}, which is backed by observational evidence.",
                        location, cid)
                    break

        # narrow population generalization
        if GENERALIZATION_RE.search(text):
            for cid in linked:
                claim = claims_by_id.get(cid)
                if claim and claim.population:
                    add("population_generalization", "warning",
                        f"Content generalises beyond the studied population of {cid}.", location, cid)
                    break

    # required caveats must not disappear
    limitations = payload.get("limitations") or []
    if not limitations:
        add("required_caveats", "error", "No limitations/caveats present — caveats must not be removed.")
    disclaimer = (payload.get("disclaimer") or "").strip()
    if not disclaimer:
        add("required_disclaimer", "error", "Disclaimer missing.")
    else:
        for phrase in DISCLAIMER_REQUIRED_PHRASES:
            if phrase.lower() not in disclaimer.lower():
                add("required_disclaimer", "error",
                    f"Disclaimer does not include the required phrase '{phrase}'.")

    # source notes must point at real sources
    valid_source_ids = {s.id for s in project.sources}
    for i, note in enumerate(payload.get("source_notes") or []):
        sid = note.get("source_id")
        if sid and sid not in valid_source_ids:
            add("citation_integrity", "error",
                f"source_notes[{i}] references source {sid}, which does not exist.", f"source_notes[{i}]")

    # format structure
    if fmt == "carousel":
        slides = payload.get("slides") or []
        if not (4 <= len(slides) <= 8):
            add("carousel_structure", "warning",
                f"Carousel has {len(slides)} slides; expected 4–8.")
        if not (payload.get("caption") or "").strip():
            add("carousel_structure", "error", "Carousel caption is missing.")
    elif fmt == "static":
        if not (payload.get("headline") or "").strip() or not (payload.get("caption") or "").strip():
            add("static_structure", "error", "Static post is missing headline or caption.")
    elif fmt == "reel":
        scenes = payload.get("scenes") or []
        if len(scenes) < 3:
            add("reel_structure", "error", "Reel needs at least 3 scenes.")
        if not (payload.get("hook") or "").strip():
            add("reel_structure", "error", "Reel hook is missing.")
        prev_end = 0.0
        for i, sc in enumerate(scenes):
            try:
                if float(sc.get("start_seconds", -1)) < prev_end - 0.01:
                    add("reel_structure", "error", f"Scene {i} starts before the previous scene ends.")
                if float(sc.get("end_seconds", 0)) <= float(sc.get("start_seconds", 0)):
                    add("reel_structure", "error", f"Scene {i} has non-positive duration.")
                prev_end = float(sc.get("end_seconds", 0))
            except (TypeError, ValueError):
                add("reel_structure", "error", f"Scene {i} has invalid timing values.")
        if not scenes or prev_end < float(payload.get("duration_seconds", 0)) - 6:
            add("reel_structure", "warning",
                "Scenes do not cover the declared duration.")
    elif fmt == "deck":
        slides = payload.get("slides") or []
        if len(slides) < 5:
            add("deck_structure", "warning",
                f"Deck has {len(slides)} slides; a research briefing usually has 8–12.")
        if not (payload.get("deck_title") or "").strip():
            add("deck_structure", "error", "Deck title is missing.")

    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]
    status = "failed" if errors else ("warnings" if warnings else "passed")

    return {
        "status": status,
        "issues": issues,
        "rules_version": RULES_VERSION,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "used_claim_ids": sorted(used_claim_ids),
        "counts": {"errors": len(errors), "warnings": len(warnings)},
        "note": "Deterministic rule-based checks; not a clinical fact-check. Doctor review still required.",
    }


def has_blocking_errors(validation: dict) -> bool:
    return any(i.get("severity") == "error" for i in (validation or {}).get("issues", []))


def claim_publication_blockers(claim: EvidenceClaim) -> list[str]:
    """Reasons this specific claim blocks publishing, independent of stored validation.

    Used by publishing eligibility as a direct claim-level gate so a stale
    'passed' validation run can never carry a blocked claim to publication.
    Mirrors the blocking rules of validate_payload (errors only).
    """
    reasons: list[str] = []
    cid = claim.id
    if claim.status == "unsupported":
        reasons.append(f"{cid} is marked UNSUPPORTED but may be used as a factual statement.")
    elif claim.status == "needs_human_review" and claim.risk_level == "high":
        reasons.append(f"{cid} is a high-risk claim still marked 'needs human review'.")
    elif claim.status == "conflicting" and claim.risk_level == "high":
        reasons.append(f"{cid} is a high-risk claim with conflicting evidence across sources.")
    if claim.status in {"supported", "partially_supported"} and not any(
        e.relation == "supports" and (e.excerpt or "").strip() for e in claim.evidence
    ):
        reasons.append(
            f"{cid} is marked '{claim.status}' but has no persisted supporting evidence passage."
        )
    return reasons


def claim_safety_checks(claim: EvidenceClaim) -> list[dict]:
    """Per-claim deterministic safety checks surfaced in the Evidence Lab.

    These mirror the language rules of validate_payload but run against the
    claim text itself so editors/doctors see risks before content is generated.
    They are NOT a clinical fact-check.
    """
    checks: list[dict] = []

    def add(rule: str, severity: str, message: str) -> None:
        checks.append({"rule": rule, "severity": severity, "message": message})

    text = claim.claim_text or ""

    if claim.status == "unsupported":
        add("evidence_status", "error",
            f"{claim.id} is marked UNSUPPORTED — it must not be stated as fact.")
    elif claim.status == "needs_human_review" and claim.risk_level == "high":
        add("evidence_status", "error",
            f"{claim.id} is a high-risk claim still marked 'needs human review'.")
    elif claim.status == "conflicting":
        sev = "error" if claim.risk_level == "high" else "warning"
        add("evidence_status", sev, f"{claim.id} has conflicting evidence across sources.")
    elif claim.status == "partially_supported":
        add("evidence_status", "warning", f"{claim.id} is only partially supported — verify wording.")

    if claim.status in {"supported", "partially_supported"} and not any(
        e.relation == "supports" and (e.excerpt or "").strip() for e in claim.evidence
    ):
        add("missing_evidence", "error",
            f"{claim.id} is marked '{claim.status}' but has no persisted supporting evidence passage.")

    if has_overclaim(text):
        add("overstatement", "error",
            "Claim contains guaranteed/miracle/proven language that overstates findings.")
    if FEAR_SHAME_RE.search(text):
        add("fear_shame", "error", "Claim uses fear-based or shaming language.")
    if DRUG_RECOMMENDATION_RE.search(text) or MED_CHANGE_RE.search(text):
        add("medication_advice", "error",
            "Claim recommends starting/stopping/changing medication or promotes a specific drug.")
    if PERSONAL_ADVICE_RE.search(text) or DIAGNOSIS_RE.search(text):
        add("personalized_advice", "error",
            "Claim gives personalized medical advice or diagnostic claims.")
    if GENERALIZATION_RE.search(text):
        add("universal_claim", "error",
            "Claim implies a universal or guaranteed outcome.")
    if CAUSAL_RE.search(text) and claim.study_design and OBSERVATIONAL_RE.search(claim.study_design):
        add("causal_overreach", "error",
            f"Causal wording used with observational evidence ({claim.study_design}).")
    return checks
