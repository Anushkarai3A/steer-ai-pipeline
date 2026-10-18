from __future__ import annotations

import re

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "of", "to", "in", "on", "for",
    "with", "at", "by", "from", "as", "is", "are", "was", "were", "be", "been", "being",
    "it", "its", "this", "that", "these", "those", "we", "our", "us", "they", "their",
    "he", "she", "his", "her", "you", "your", "i", "me", "my", "not", "no", "than",
    "into", "over", "under", "between", "about", "after", "before", "during", "per",
    "also", "such", "can", "may", "could", "would", "should", "will", "shall", "do",
    "does", "did", "have", "has", "had", "there", "here", "when", "while", "who",
    "which", "what", "how", "more", "most", "some", "any", "all", "each", "both",
    "up", "out", "so", "only", "other", "use", "used", "using", "one", "two",
}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'\(])")


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    parts = _SENTENCE_SPLIT.split(text)
    return [p.strip() for p in parts if p.strip() and len(p.strip()) > 20]


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9%]+", text.lower()) if t not in STOPWORDS and len(t) > 1]


NUM_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|percent|kg|mg|g|ml|mmol|bpm|years?|months?|weeks?|days?|hours?|points?|times)?", re.I)
NUMBERS_RE = re.compile(r"\d+(?:\.\d+)?")


def extract_numbers(text: str) -> list[str]:
    return [n.replace(" ", "") for n in NUMBERS_RE.findall(text)]


def token_overlap(a: str, b: str) -> float:
    ta, tb = set(tokenize(a)), set(tokenize(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


NEGATION_RE = re.compile(
    r"\b(not|no|never|neither|nonsignificant|non-significant|failed to|did not|does not|"
    r"was not|were not|no significant|absence of|without)\b",
    re.I,
)


def has_negation(text: str) -> bool:
    return bool(NEGATION_RE.search(text))


OVERCLAIM_RE = re.compile(
    r"\b(cure|cures|cured|guarantee|guaranteed|miracle|always|never fails|(?<!-)(?:proves?|proven)|"
    r"reverses?|eliminates?|instantly|everyone|completely prevent|prevent any|"
    r"100\s*%|drop\s*in\s*days|breakthrough)\b",
    re.I,
)


def has_overclaim(text: str) -> bool:
    return bool(OVERCLAIM_RE.search(text))
