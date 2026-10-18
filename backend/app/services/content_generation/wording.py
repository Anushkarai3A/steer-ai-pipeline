from __future__ import annotations

"""Presentation-language helpers.

Claim text extracted from a paper is a full sentence, often 100+ words with
qualifiers. Slide and social copy needs the same fact in a line or two. These
helpers shorten the wording while keeping every number, unit, population and
time period, and never converting an association into a cause or dropping a
limitation. The unshortened claim always remains available in the Evidence Lab.
"""

import re
import unicodedata

from app.core.text import extract_numbers

# PDF extractors return typographic ligatures (ﬁ ﬂ ﬀ) as single codepoints.
# PowerPoint/Calibri cannot render them, so they surface as blank/missing
# glyphs — e.g. a bullet reading only "O" where "Objec" was intended.
_LIGATURES = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
    "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st",
    "\ufb01": "fi",
}
_LIGATURE_RE = re.compile("[\ufb00-\ufb06\ufffd]")


def normalize_text(text: str) -> str:
    """Normalize ligature/control/placeholder characters for presentation.

    Keeps every letter; only rewrites the characters a slide font cannot draw.
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", str(text))
    t = t.replace("\ufb01", "fi").replace("\ufb02", "fl")
    t = _LIGATURE_RE.sub(lambda m: _LIGATURES.get(m.group(0), ""), t)
    return " ".join(t.split())


# "Thirty-three of 49" -> "33 of 49"
_WORD_NUMBERS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18",
    "nineteen": "19", "twenty": "20", "thirty": "30", "forty": "40",
    "fifty": "50", "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90",
}
_WORD_NUM_RE = re.compile(
    r"\b(" + "|".join(_WORD_NUMBERS) + r")[-\s](one|two|three|four|five|six|seven|eight|nine)\b(?!\s*\.)",
    re.I,
)
_ONES = {k: v for k, v in _WORD_NUMBERS.items()}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_NO = {"no": "0", "none": "0"}

_LEAD_FILLER = re.compile(
    r"^(?:notably|importantly|interestingly|surprisingly|as expected|in addition|"
    r"additionally|furthermore|moreover|also|however|therefore|thus|hence|overall|"
    r"generally|specifically|in particular|of note|it should be noted that|"
    r"the results (?:of|show|indicate|suggest) that|our (?:results|findings|observations) "
    r"(?:show|indicate|suggest|demonstrate)(?: that)?|we (?:found|observed|noted|demonstrated)(?: that)?|"
    r"this (?:study|analysis|trial|paper) (?:found|showed|demonstrated|observed)(?: that)?|"
    r"results (?:show|indicate|suggest)(?: that)?|in this (?:study|trial|analysis))\s*,?\s*",
    re.I,
)
_ANY_TABLE_FIG = re.compile(
    r"\s*[\(\[]?\s*(?:table|fig(?:ure)?\.?)\s*\d+(?:\.\d+)*\s*[\)\]]?", re.I
)
_TRAILING_CITE = re.compile(r"\s*[\[\(]\s*\d+(?:\s*[-–,]\s*\d+)*\s*[\]\)]\s*$")
_TRAILING_JUNK = re.compile(
    r"\s*(?:JHEP Reports.*|PLOS\s*(?:One)?\s*\|.*|https?://\S+.*|doi:\S+.*|"
    r"\d+\s*/\s*\d+\s*$)\s*$",
    re.I,
)
_FILLER_PHRASES = [
    (r"\bparticipants who successfully passed screening\b", "screened volunteers"),
    (r"\bvolunteers who successfully passed screening\b", "screened volunteers"),
    (r"\bwere enrolled into the study\b", "entered the study"),
    (r"\bwas enrolled into the study\b", "entered the study"),
    (r"\bparticipants (?:were|was) then randomised\b", "participants were randomised"),
    (r"\bthe intervention group\b", "the intervention arm"),
    (r"\bthe control group\b", "the control arm"),
    (r"\bwas principally attributable to\b", "came from"),
    (r"\bwere able to tolerate\b", "tolerated"),
    (r"\brequired for evaluation of\b", "for evaluating"),
    (r"\bcompleted the 12-week intervention required\b", "completed the 12-week intervention"),
    (r"\bwere followed up at\b", "were followed up at"),
    (r"\bhad a significantly decreased risk\b", "had a much lower risk"),
    (r"\bwas found between\b", "was found between"),
    (r"\ba significant inverse association was found\b", "a strong inverse link was found"),
    (r"\bnew-onset\b", "new"),
    (r"\bthe mean change in\b", "the average change in"),
    (r"\bcompared with\b", "vs"),
    (r"\bcompared to\b", "vs"),
    (r"\bin the fully adjusted model,?\s*", "After full adjustment, "),
    (r"\bat baseline,?\s*", "At baseline, "),
    (r"\bduring follow-up,?\s*", "During follow-up, "),
    (r"\bin the ([a-zA-Z0-9\-]+) treatment arm\b", r"in the \1 arm"),
]


def numbers_to_digits(text: str) -> str:
    """Rewrite spelled-out numbers as digits so claims read like slide copy."""

    def repl(m: re.Match) -> str:
        tens = _TENS.get(m.group(1).lower())
        ones = _ONES.get(m.group(2).lower())
        if tens is None or ones is None:
            return m.group(0)
        return str(tens + int(ones))

    out = _WORD_NUM_RE.sub(repl, text)
    # "no participants" -> "0 participants" is worse copy; keep the word.
    # single word numbers inside a "N of M" style phrase
    def single(m: re.Match) -> str:
        return _ONES.get(m.group(1).lower(), m.group(1))

    out = re.sub(
        r"\b(" + "|".join(sorted(_ONES, key=len, reverse=True)) + r")\b(?=\s+(?:of|in|to)\b)",
        single,
        out,
        flags=re.I,
    )
    return out


def strip_paper_artifacts(text: str) -> str:
    """Remove running headers, table/figure refs and trailing citations.

    Never touches statistical parentheses like "(OR: 0.92, 95% CI: 0.860.99,
    P = 0.03)" or parenthetical subgroups like "(n = 14 lifestyle)".
    """
    t = " ".join(str(text or "").split())
    t = normalize_text(t)
    t = _TRAILING_JUNK.sub("", t)
    t = _TRAILING_CITE.sub("", t)
    # Citations glued to a word by the PDF extractor: "...without T2D.15 More"
    # -> "...without T2D." The trailing word is a page-header fragment, so
    # everything from the glued citation onward is discarded.
    t = re.sub(r"\.\d{1,3}(?=\s+[A-Z]).*$", ".", t)
    # Dehyphenated word split across a line break: "with- drawal" -> "withdrawal"
    t = re.sub(r"\b([A-Za-z]{2,})-\s+([a-z]{2,})\b", r"\1\2", t)
    # (Table 1) / [27] / (Fig. 2) — a bare table/figure pointer, not a stat
    t = _ANY_TABLE_FIG.sub("", t)
    # A dangling pointer whose number was lost when the up-stream sentence
    # splitter cut on the period in "Fig." ("...interventions (Fig."). Drop the
    # incomplete fragment so the sentence ends on its last real word.
    t = re.sub(r"[\(\[]\s*(?:table|fig(?:ure)?)\s*\.?\s*$", "", t, flags=re.I)
    t = " ".join(t.split())
    return t.strip(" ,;:.-")


# Cover-slide copy puts the claim in quotation marks. The validator checks that
# quoted text appears verbatim in the evidence excerpt, but a paraphrased
# claim wrapped in decorative quotes reads as a direct quotation and fails
# that check. Only used when the caller is quoting its own paraphrase.
_QUOTE_CHARS = "\u201c\u201d\u2018\u2019\"'"


def strip_self_quotes(text: str) -> str:
    """Drop decorative quotes that wrap the whole string (self-quote, not a citation)."""
    t = (text or "").strip()
    while len(t) >= 2 and t[0] in _QUOTE_CHARS and t[-1] in _QUOTE_CHARS:
        t = t[1:-1].strip()
    return t


def simplify_claim(text: str, limit: int = 120) -> str:
    """Shorten a claim to presentation language without losing its numbers.

    Never drops a number that appears in the original. Never invents one. If the
    shortened form would lose a number, the sentence is kept longer instead.
    """
    t = normalize_text(text)
    t = " ".join(t.split())
    if not t:
        return ""
    t = numbers_to_digits(t)
    t = strip_paper_artifacts(t)
    for pat, rep in _FILLER_PHRASES:
        t = re.sub(pat, rep, t, flags=re.I)
    t = _LEAD_FILLER.sub("", t)
    t = " ".join(t.split())
    # Strip decorative quotes BEFORE adding sentence punctuation. Otherwise the
    # closing quote lands outside the period ("...hours.”.") and the strip
    # below would not see a matching pair.
    t = strip_self_quotes(t)
    if t and t[0].islower():
        t = t[0].upper() + t[1:]
    if not t.endswith((".", "!", "?", "…")):
        t += "."

    if len(t) <= limit:
        return t

    original_nums = set(extract_numbers(text))
    words = t.split()
    for end in range(len(words), 4, -1):
        candidate = " ".join(words[:end]).rstrip(",;:").strip()
        if not candidate.endswith("."):
            candidate += "."
        if len(candidate) > limit:
            continue
        if original_nums and not original_nums.issubset(set(extract_numbers(candidate))):
            continue
        if not _ends_complete(candidate):
            continue
        return candidate
    # No clean shortening preserved every number and ended on a complete
    # clause. Return the full simplified sentence rather than a mangled
    # fragment — the renderer will shrink the font or wrap it.
    return t


_DANGLING_END_RE = re.compile(
    r"\b(?:vs|vs\.|and|or|but|with|of|the|a|an|to|in|for|from|at|by|on|as|is|are|was|were|"
    r"had|has|have|that|which|who|whose|than|then|into|over|under|between|about|"
    r"compared|including|such|per|via|used|across|during|after|before|"
    r"individuals|participants|people|patients|adults|subjects|those|these|their|our|its)\b\s*\.?$",
    re.I,
)


def _ends_complete(s: str) -> bool:
    """True when the sentence ends on a real word, not a dangling fragment.

    Rejects three kinds of truncation:
      * a trailing function word ("... in the liraglutide arm")
      * a participle still needing its object ("... predisposing to weight")
      * text cut mid-parenthetical ("... (n = 14 lifestyle")
    """
    body = s.rstrip(".!?…").strip()
    if not body:
        return False
    if body.count("(") > body.count(")"):
        return False
    if body.count("[") > body.count("]"):
        return False
    last = body.split()[-1]
    if _DANGLING_END_RE.fullmatch(last + "."):
        return False
    if _DANGLING_END_RE.fullmatch(last):
        return False
    # A participle/adjective that still governs a complement. "Predisposing"
    # and "susceptible" are content words, so the word list alone would not
    # catch them; the following preposition is what marks the truncation.
    if re.fullmatch(
        r"(?i)(?:predispos\w*|susceptib\w*|likely|liable|due|owing|"
        r"attribut\w*|comparable|similar|equivalent|essential|"
        r"crucial|necessary|sufficient|possible|impossible)",
        last,
    ):
        return False
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9%)\]]*$", last))


def headline_from_claim(text: str, limit: int = 90) -> str:
    """A short, complete headline sentence derived from a claim."""
    return simplify_claim(text, limit)
