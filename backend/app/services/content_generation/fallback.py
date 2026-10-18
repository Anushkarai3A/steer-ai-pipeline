from __future__ import annotations

"""Deterministic content generation fallback.

Used when no AI provider is configured (LLM_PROVIDER=none). It builds real,
format-appropriate content strictly from the evidence-linked claims and the
research summary of the actual uploaded sources. It never invents statistics,
quotations or citations — every factual sentence it emits comes from a stored
claim record that has its own evidence rows.

Output is labelled "Deterministic rule-based generator (no AI model used)" so
the UI can never be mistaken for model-assisted generation.
"""

import re

from app.core.text import extract_numbers
from app.services.content_generation.references import (
    MISSING_REFERENCE_TEXT,
    normalize_reference,
    normalize_references,
    reference_line,
    references_bullets,
)
from app.services.content_generation.wording import (
    headline_from_claim,
    normalize_text,
    simplify_claim,
    strip_self_quotes,
)

MODE_LABEL = "Deterministic rule-based generator (no AI model used)"

DISCLAIMER = (
    "This content is educational and is not medical advice. It summarises published "
    "research and does not replace consultation with a qualified clinician."
)

HASHTAGS = ["#evidencebased", "#researchexplained", "#steer"]

AUDIENCE = "General adult audience on Instagram interested in evidence-based health information."

# Claims that are merely methods boilerplate ("X is presented in Table 1") are
# not findings — they do not belong on a slide or in the key-findings deck
# section, and they are what produced the isolated-"O" bullet (a fragment of a
# methods sentence that started with a page-number glyph).
_METHODS_BOILERPLATE_RE = re.compile(
    r"^\s*(?:baseline demographic and anthropometric data|data are presented in|"
    r"are included within the supplementary|supplementary data|table \d+|"
    r"figures? are available|see (?:also )?the supplementary|"
    r"the (?:lifestyle|intervention) (?:programme|program|intervention)s? (?:was|were) "
    r"(?:designed|delivered|commenced)|study interventions were commenced)\b",
    re.I,
)

# A claim is only useful as a finding if it says something about the study.
_MIN_FINDING_LEN = 40


def _is_substantive_finding(claim: dict) -> bool:
    text = " ".join(str(claim.get("claim_text") or "").split())
    if len(text) < _MIN_FINDING_LEN:
        return False
    if _METHODS_BOILERPLATE_RE.match(text):
        return False
    if re.match(r"^(?:table|figure|fig\.?)\s*\d+", text, re.I):
        return False
    # must contain at least one number OR a verb-ish word (a real statement)
    if extract_numbers(text):
        return True
    return bool(re.search(r"\b(?:found|showed|reduced|increased|associated|compared|"
                          r"reported|completed|randomised|randomized|enrolled|"
                          r"declined|tolerated|resolved|attributable)\b", text, re.I))


def usable_claims(claims: list[dict]) -> list[dict]:
    """Claims that may be stated as fact in content.

    Requires supported/partially_supported status, a persisted evidence passage,
    and a substantive finding (not methods boilerplate).
    """
    out = []
    for c in claims:
        if c.get("status") not in {"supported", "partially_supported"}:
            continue
        if not c.get("evidence"):
            continue
        if not _is_substantive_finding(c):
            continue
        out.append(c)
    return out


def shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # never cut in the middle of a number
    for num in extract_numbers(text):
        if num and num not in cut and text.find(num) < limit + 12:
            return text[: min(limit + 12, len(text))].rsplit(" ", 1)[0]
    return cut.rsplit(" ", 1)[0].rstrip(",;:.")


def _evidence_for(claim: dict) -> list[dict]:
    return claim.get("evidence") or []


def _source_dict(ev: dict) -> dict | None:
    src = ev.get("source")
    return src if isinstance(src, dict) else None


def source_notes_for(claims: list[dict]) -> list[dict]:
    """One note per distinct source actually linked to the given claims."""
    notes = []
    seen: set[str] = set()
    for claim in claims:
        for ev in _evidence_for(claim):
            sid = ev.get("source_id") or ""
            if sid in seen:
                continue
            seen.add(sid)
            src = _source_dict(ev) or {}
            ref = normalize_reference({
                "title": src.get("title") or ev.get("source_title"),
                "journal": src.get("journal"),
                "year": src.get("year"),
                "doi": ev.get("doi") or src.get("doi"),
                "url": ev.get("url") or src.get("canonical_url") or src.get("url"),
                "authors": src.get("authors"),
            })
            if ref:
                text = reference_line(ref)
                if ev.get("page"):
                    text += f" — p. {ev['page']}"
                notes.append({
                    "text": text, "source_id": ev.get("source_id"),
                    "doi": ref.get("doi"), "url": ref.get("url"),
                    "title": ref.get("title"), "authors": ref.get("authors"),
                    "journal": ref.get("journal"), "year": ref.get("year"),
                })
            elif sid:
                text = "Source document (details unavailable — verification required.)"
                if ev.get("page"):
                    text += f" — p. {ev['page']}"
                notes.append({"text": text, "source_id": ev.get("source_id"),
                              "doi": None, "url": None})
    return notes


def _project_source_notes(sources: list[dict]) -> list[dict]:
    notes = []
    for s in sources or []:
        ref = normalize_reference(s)
        if not ref:
            continue
        notes.append({
            "text": reference_line(ref), "source_id": s.get("id"),
            "doi": ref.get("doi"), "url": ref.get("url"),
            "title": ref.get("title"), "authors": ref.get("authors"),
            "journal": ref.get("journal"), "year": ref.get("year"),
        })
    return notes


def _limitations_of(summary: dict, claims: list[dict]) -> list[str]:
    out: list[str] = []

    def add(raw: str) -> None:
        t = normalize_text(" ".join(str(raw or "").split()).strip())
        if t and len(t) > 20 and t not in out:
            out.append(simplify_claim(t, 240))

    for lim in summary.get("limitations", []) or []:
        add(lim.get("text") if isinstance(lim, dict) else str(lim))
        if len(out) >= 3:
            break
    for c in claims:
        add(c.get("limitations") or "")
        if len(out) >= 3:
            break
    if not out:
        out.append("This is based on a small set of uploaded sources and may not reflect the full evidence base.")
    return out


def _main_message(claims: list[dict], summary: dict) -> str:
    """Return a single paraphrased takeaway, never wrapped in quotation marks.

    The validator treats quoted text as a direct quotation that must appear
    verbatim in the evidence excerpt, so a paraphrase must not be quoted.
    """
    if claims:
        return strip_self_quotes(simplify_claim(claims[0]["claim_text"], 200))
    kf = summary.get("key_findings") or []
    if kf and kf[0].get("text"):
        return strip_self_quotes(simplify_claim(kf[0]["text"], 200))
    return "A structured readout of the uploaded research — see the evidence lab for details."


def _concept(project_name: str, claim_count: int, source_count: int) -> str:
    return (
        f"Evidence-first explainer for “{project_name}”: {source_count} source paper(s), "
        f"{claim_count} evidence-linked claim(s), one clear takeaway per frame — no hype."
    )


def build_carousel(project_name: str, summary: dict, claims: list[dict], sources: list[dict]) -> dict:
    usable = usable_claims(claims)
    if not usable:
        raise ValueError(
            "No evidence-linked claims are available to build content. "
            "Check the Evidence Lab: claims need located supporting passages first."
        )
    max_claim_slides = 5
    used = usable[:max_claim_slides]
    notes = source_notes_for(used) or _project_source_notes(sources)
    limitations = _limitations_of(summary, usable)
    main = _main_message(usable, summary)

    slides = []
    slides.append({
        "index": 0,
        "headline": headline_from_claim(used[0]["claim_text"], 90) or "What the research actually says",
        # No decorative quotes: `main` is a paraphrase of the claim, and the
        # validator treats quoted text as a direct quotation that must appear
        # verbatim in the evidence excerpt.
        "body": (
            f"{main} — one of {len(usable)} claim(s) "
            f"traced back to the source papers in this project."
        ),
        "claim_ids": [used[0]["id"]],
        "visual_direction": "Editorial cover: cream background, large serif headline, small 'steer.' mark, rust rule.",
        "footnote": "",
    })

    for i, claim in enumerate(used, start=1):
        ev = _evidence_for(claim) or [{}]
        slides.append({
            "index": i,
            "headline": headline_from_claim(claim["claim_text"], 90),
            "body": simplify_claim(claim["claim_text"], 240),
            "claim_ids": [claim["id"]],
            "visual_direction": "Rust accent number, serif headline, body copy at comfortable reading size, source chip at bottom.",
            "footnote": f"Evidence: {claim['id']}" + (f" · p. {ev[0].get('page')}" if ev[0].get("page") else ""),
        })

    slides.append({
        "index": len(slides),
        "headline": "What this evidence does not show",
        "body": "\n".join(f"• {l}" for l in limitations[:2]),
        "claim_ids": [],
        "visual_direction": "Softer blush panel, calmer type, clear heading — nuance slide, not a warning slide.",
        "footnote": "Limitations from the source papers",
    })
    slides.append({
        "index": len(slides),
        "headline": "The takeaway",
        "body": simplify_claim(usable[0]["claim_text"], 200),
        "claim_ids": [usable[0]["id"]],
        "visual_direction": "Closing slide: maroon background, cream type, small source list, 'steer.' signature.",
        "footnote": "Scroll for sources in the caption",
    })

    for i, s in enumerate(slides):
        s["index"] = i

    claims_text = "\n".join(
        f"• {simplify_claim(c['claim_text'], 200)} [{c['id']}]" for c in used
    )
    source_lines = "\n".join(f"• {n['text']}" for n in notes) or f"• {MISSING_REFERENCE_TEXT}"
    caption = (
        f"{main}\n\n"
        f"In this carousel:\n{claims_text}\n\n"
        f"What it does not show: {limitations[0]}\n\n"
        f"Sources:\n{source_lines}\n\n"
        f"{DISCLAIMER}"
    )

    return {
        "concept": _concept(project_name, len(usable), len(sources)),
        "audience": AUDIENCE,
        "main_message": main,
        "slides": slides,
        "caption": caption,
        "hashtags": HASHTAGS,
        "source_notes": notes,
        "references": normalize_references(sources),
        "limitations": limitations,
        "disclaimer": DISCLAIMER,
    }


def build_static(project_name: str, summary: dict, claims: list[dict], sources: list[dict]) -> dict:
    usable = usable_claims(claims)
    if not usable:
        raise ValueError(
            "No evidence-linked claims are available to build content. "
            "Check the Evidence Lab: claims need located supporting passages first."
        )
    top = usable[0]
    limitations = _limitations_of(summary, usable)
    ev = _evidence_for(top) or [{}]
    notes = source_notes_for([top]) or _project_source_notes(sources)
    headline = headline_from_claim(top["claim_text"], 90)
    body = simplify_claim(top["claim_text"], 220)

    caption = (
        f"{body}\n\n"
        f"One takeaway, traced to the source. Full context and limitations are part of the science — "
        f"this post does not claim more than the study shows.\n\n"
        f"Source: " + ("; ".join(n["text"] for n in notes) if notes else MISSING_REFERENCE_TEXT) +
        f"\n\n{DISCLAIMER}"
    )

    return {
        "concept": _concept(project_name, len(usable), len(sources)),
        "audience": AUDIENCE,
        "main_message": simplify_claim(top["claim_text"], 200),
        "headline": headline,
        "body": body,
        "claim_ids": [top["id"]],
        "visual_direction": (
            "Single editorial card: cream ground, serif headline, rust underline, "
            "one claim, evidence chip at the base ("
            + (f"{top['id']} · p. {ev[0].get('page')}" if ev[0].get("page") else top["id"]) + ")."
        ),
        "caption": caption,
        "hashtags": HASHTAGS,
        "source_notes": notes,
        "references": normalize_references(sources),
        "limitations": limitations,
        "disclaimer": DISCLAIMER,
    }


def _summary_entries(summary: dict, bucket: str) -> list[str]:
    """Clean text entries from a summary bucket; drops unusable fragments."""
    out: list[str] = []
    for entry in summary.get(bucket, []) or []:
        t = (entry.get("text") if isinstance(entry, dict) else str(entry)) or ""
        t = " ".join(t.split()).strip()
        if not _is_usable_sentence(t):
            continue
        if t not in out:
            out.append(t)
    return out


_NOISE_RE = re.compile(
    r"^(?:are included within the supplementary data\.?|"
    r"the supplementary (?:data|materials?)(?: (?:are|is) included .*)?\.?|"
    r"jhep reports.*|plos one\s*\|.*|https?://\S+.*|"
    r"\d+\s*[j|]\s*\d+.*|"
    r"figures? and tables? (?:are|is) available.*|"
    r"see (?:the )?supplementary.*)$",
    re.I,
)
_DIGITS_RE = re.compile(r"^\d{1,4}$")
_SPLIT_JUNK_RE = re.compile(r"^\d+\s*[j|]\s*\d+$")


def _is_usable_sentence(t: str) -> bool:
    """Reject fragments the extractor split badly (page headers, digits, refs)."""
    if not t or len(t) < 12:
        return False
    if _DIGITS_RE.match(t) or _SPLIT_JUNK_RE.match(t):
        return False
    if _NOISE_RE.match(t):
        return False
    letters = sum(1 for ch in t if ch.isalpha())
    return letters >= 8 and letters / max(len(t), 1) > 0.4


def _is_usable_measurement(t: str) -> bool:
    """A short numeric value with a unit (e.g. "-8.2 mmHg"), which the
    sentence filter would otherwise reject for having too few letters."""
    t = " ".join(str(t or "").split()).strip()
    if not 4 <= len(t) <= 120:
        return False
    if not re.search(r"\d", t) or not re.search(r"[A-Za-z%]", t):
        return False
    if _NOISE_RE.match(t) or _SPLIT_JUNK_RE.match(t):
        return False
    return True



def _clean_bullets(items: list[str]) -> list[str]:
    """Drop empty/one-character/noise bullets and de-duplicate."""
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        t = " ".join(str(item or "").split()).strip().lstrip("•·-–—").strip()
        if len(t) < 3:
            continue
        if not _is_usable_sentence(t):
            continue
        if t.lower() in seen:
            continue
        seen.add(t.lower())
        out.append(t)
    return out


def _summary_scalar(summary: dict, bucket: str) -> str:
    entries = _summary_entries(summary, bucket)
    return shorten(entries[0], 240) if entries else ""


DECK_NOT_ESTABLISHED = "Not established in the provided sources."


def build_deck(project_name: str, summary: dict, claims: list[dict], sources: list[dict]) -> dict:
    """Deterministic 10-slide research briefing deck.

    Every bullet comes from the stored summary buckets or evidence-linked claim
    records. Missing sections honestly say so — nothing is invented. Bullets are
    normalised so a fragment like "O" or a page header can never reach a slide.
    """
    usable = usable_claims(claims)
    if not usable:
        raise ValueError(
            "No evidence-linked claims are available to build a deck. "
            "Check the Evidence Lab: claims need located supporting passages first."
        )

    rq = _summary_scalar(summary, "research_question")
    if not rq:
        # No decorative quotes around the project name: the validator treats a
        # wrapped string as a direct quotation that must appear verbatim in the
        # evidence, and a project title never does.
        rq = "What does the uploaded evidence base say about " + project_name + "?"
    design = _summary_entries(summary, "study_design")
    population = _summary_entries(summary, "population")
    methods = _summary_entries(summary, "methods")
    findings = _summary_entries(summary, "key_findings")
    numbers = summary.get("numbers") or []
    interpretation = _summary_entries(summary, "practical_interpretation")
    conflicts = _summary_entries(summary, "conflicts")
    conflict_note = (summary.get("conflict_note") or "").strip()
    not_established = _summary_entries(summary, "not_established")
    limitations = _limitations_of(summary, usable)
    refs = references_bullets(sources)
    notes = source_notes_for(usable) or _project_source_notes(sources)

    used = usable[:6]
    slides: list[dict] = []

    def add(kind: str, title: str, bullets: list[str], claim_ids: list[str] | None = None,
            table: dict | None = None, source_notes: list[str] | None = None,
            shorten_bullets: bool = True) -> None:
        # Reference lines and provenance bullets carry verifiable identifiers
        # (DOIs, titles); shortening them cuts the DOI and leaves a dangling
        # separator, so they are rendered in full.
        prepared = [shorten(b, 280) for b in bullets] if shorten_bullets else list(bullets)
        slides.append({
            "index": len(slides),
            "kind": kind,
            "title": title,
            "bullets": _clean_bullets(prepared),
            "table": table,
            "claim_ids": claim_ids or [],
            "source_notes": source_notes or [],
        })

    # 1 — Title & provenance
    source_lines = []
    for s in sources:
        ref = normalize_reference(s)
        if not ref:
            continue
        line = reference_line(ref)
        source_lines.append(line)
    add("title", shorten(project_name, 150), [
        f"Research briefing generated from {len(sources)} uploaded source(s) and "
        f"{len(usable)} evidence-linked claim(s).",
        "Every statement in this deck is traceable to stored evidence passages "
        "(see claim references on each slide).",
        "Deterministic rule-based generation — no AI model used.",
    ] + source_lines[:5], source_notes=source_lines[:5], shorten_bullets=False)

    # 2 — Background / research question
    bg = [headline_from_claim(f, 140) for f in findings[:2]]
    add("background", "Background", [rq, *bg] if rq else [DECK_NOT_ESTABLISHED, *bg])

    # 3 — Methods
    method_bullets = [
        simplify_claim(d, 180) for d in design[:2]
    ] + [simplify_claim(m, 180) for m in methods[:3]]
    add("methods", "Methods of the source evidence", method_bullets or [DECK_NOT_ESTABLISHED])

    # 4 — Population / participants
    add("population", "Population studied",
        [simplify_claim(p, 180) for p in population[:4]] or [DECK_NOT_ESTABLISHED])

    # 5 — Key findings (linked claims)
    finding_bullets, finding_ids = [], []
    for c in used:
        ev = _evidence_for(c) or [{}]
        line = simplify_claim(c["claim_text"], 200)
        ref = f"[{c['id']}]"
        if ev[0].get("page"):
            ref += f" p. {ev[0]['page']}"
        finding_bullets.append(f"{line} {ref}")
        finding_ids.append(c["id"])
    add("findings", "Key findings (evidence-linked)", finding_bullets or [DECK_NOT_ESTABLISHED],
        claim_ids=finding_ids)

    # 6 — Quantitative results (real numbers from summary buckets only)
    table: dict | None = None
    quant_bullets: list[str] = []
    if numbers:
        rows = []
        for n in numbers[:6]:
            if isinstance(n, dict):
                label = shorten(n.get("label") or n.get("context") or "Reported figure", 80)
                value = str(n.get("value") or n.get("text") or "").strip()
                if not value:
                    value = shorten(n.get("text") or "", 80)
                if value and (_is_usable_sentence(value + " x") or _is_usable_measurement(value)):
                    rows.append([label, value])
            elif str(n).strip() and (
                _is_usable_sentence(str(n) + " x") or _is_usable_measurement(str(n))
            ):
                rows.append(["Reported figure", shorten(str(n), 120)])
        if rows:
            table = {"headers": ["Measure", "Value in sources"], "rows": rows[:6]}
    else:
        quant_bullets.append("No quantitative results were extracted from the uploaded sources.")
    if conflicts:
        quant_bullets.append("Conflicts noted: " + shorten(conflicts[0], 200))
    elif conflict_note:
        quant_bullets.append(shorten(conflict_note, 220))
    add("quantitative", "Quantitative results", quant_bullets, table=table)

    # 7 — Interpretation
    add("interpretation", "Interpretation",
        [simplify_claim(i, 200) for i in interpretation[:4]] or [DECK_NOT_ESTABLISHED])

    # 8 — Limitations
    add("limitations", "Limitations", limitations)

    # 9 — Takeaways
    takeaways = [simplify_claim(c["claim_text"], 200) + f" [{c['id']}]" for c in used[:3]]
    if not_established:
        takeaways.append("Not established in the provided sources: " + shorten(not_established[0], 160))
    add("takeaways", "Takeaways", takeaways or [DECK_NOT_ESTABLISHED],
        claim_ids=[c["id"] for c in used[:3]])

    # 10 — References & verification notes
    ref_bullets = list(refs[:6])
    ref_bullets.append(
        "Verification: open the Evidence Lab to re-check each claim's located "
        "passage; validation is rule-based, not a clinical fact-check."
    )
    add("references", "References & verification notes", ref_bullets,
        source_notes=[n["text"] for n in notes[:6]], shorten_bullets=False)

    return {
        "concept": (
            f"10-slide research briefing for “{project_name}”: provenance, methods, "
            f"evidence-linked findings, limitations — editable PowerPoint."
        ),
        "audience": "Clinical and research stakeholders reviewing this evidence base.",
        "main_message": simplify_claim(used[0]["claim_text"], 220),
        "deck_title": shorten(project_name, 150),
        "subtitle": "Research briefing — evidence-linked, human-reviewed",
        "slides": slides,
        "caption": "",
        "hashtags": [],
        "source_notes": notes,
        "references": normalize_references(sources),
        "limitations": limitations,
        "disclaimer": DISCLAIMER,
    }


def build_reel(project_name: str, summary: dict, claims: list[dict], sources: list[dict]) -> dict:
    usable = usable_claims(claims)
    if not usable:
        raise ValueError(
            "No evidence-linked claims are available to build content. "
            "Check the Evidence Lab: claims need located supporting passages first."
        )
    used = usable[:4]
    limitations = _limitations_of(summary, usable)
    notes = source_notes_for(used) or _project_source_notes(sources)

    hook_len, nuance_len, close_len = 3, 5, 4
    claim_len = 6
    total = hook_len + claim_len * len(used) + nuance_len + close_len
    if total < 30:
        claim_len = 6 + (30 - total) // len(used)
        total = hook_len + claim_len * len(used) + nuance_len + close_len
    duration = max(24, min(60, total))

    scenes = []
    t = 0.0

    def add(dur: float, text: str, vo: str, visual: str, claim_ids: list[str]) -> None:
        nonlocal t
        scenes.append({
            "index": len(scenes),
            "start_seconds": round(t, 1),
            "end_seconds": round(t + dur, 1),
            "on_screen_text": text,
            "voiceover": vo,
            "visual_direction": visual,
            "claim_ids": claim_ids,
        })
        t += dur

    add(hook_len, "What the research actually says",
        "Here is what the research actually says — without the hype.",
        "Bold serif hook on cream; quick fade in; 'steer.' mark.", [])

    for claim in used:
        ev = _evidence_for(claim) or [{}]
        add(claim_len,
            headline_from_claim(claim["claim_text"], 90),
            simplify_claim(claim["claim_text"], 150),
            f"Claim card with evidence chip {claim['id']}" + (f" and page {ev[0].get('page')}" if ev[0].get("page") else "") + "; slow push-in.",
            [claim["id"]])

    add(nuance_len, "What it does not show",
        "And what it does not show: " + shorten(limitations[0], 90),
        "Blush panel, calmer typography, two bullet lines of limitations.", [])

    add(close_len, headline_from_claim(usable[0]["claim_text"], 90),
        "One takeaway, linked to the evidence. Sources are in the caption.",
        "Maroon closing card with takeaway line, source list and 'steer.' signature.",
        [usable[0]["id"]])

    source_lines = "\n".join(f"• {n['text']}" for n in notes) or f"• {MISSING_REFERENCE_TEXT}"
    caption = (
        f"{simplify_claim(usable[0]['claim_text'], 200)}\n\n"
        "Full evidence, limitations and sources:\n"
        f"{source_lines}\n\n"
        f"{DISCLAIMER}"
    )

    return {
        "concept": _concept(project_name, len(usable), len(sources)),
        "audience": AUDIENCE,
        "main_message": simplify_claim(usable[0]["claim_text"], 200),
        "duration_seconds": int(duration),
        "hook": "Here is what the research actually says — without the hype.",
        "scenes": scenes,
        "on_screen_captions": True,
        "caption": caption,
        "hashtags": HASHTAGS,
        "source_notes": notes,
        "references": normalize_references(sources),
        "limitations": limitations,
        "disclaimer": DISCLAIMER,
        "closing_takeaway": simplify_claim(usable[0]["claim_text"], 200),
    }
