"""
Keyword-based sentiment scoring for tweet text.

Returns a score in [-1.0, 1.0] and a label: "bullish" | "bearish" | "neutral".
"""

import json
import re
import logging
from config import DATA_DIR

logger = logging.getLogger(__name__)


def _load_keywords() -> dict[str, list[str]]:
    path = DATA_DIR / "sentiment_keywords.json"
    try:
        return json.loads(path.read_text())
    except Exception as e:
        logger.warning("Could not load sentiment_keywords.json: %s", e)
        return {"bullish": [], "bearish": [], "neutral": []}


_KW = _load_keywords()
_BULLISH: set[str] = {k.lower() for k in _KW.get("bullish", [])}
_BEARISH: set[str] = {k.lower() for k in _KW.get("bearish", [])}

# Simple negation words — flip sentiment of next keyword
_NEGATIONS = {"not", "no", "never", "don't", "doesn't", "didn't", "won't",
              "isn't", "aren't", "wasn't", "weren't", "nor", "neither"}


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b[\w']+\b", text.lower())


def score(text: str) -> tuple[float, str]:
    """
    Returns (score, label).
    score: -1.0 (very bearish) … 0.0 (neutral) … +1.0 (very bullish)
    """
    tokens = _tokenize(text)
    bullish_hits = 0
    bearish_hits = 0
    negate = False

    # Also check bigrams / trigrams against multi-word keywords
    phrase_text = text.lower()

    for kw in _BULLISH:
        if " " in kw:
            count = phrase_text.count(kw)
            bullish_hits += count
    for kw in _BEARISH:
        if " " in kw:
            count = phrase_text.count(kw)
            bearish_hits += count

    for i, tok in enumerate(tokens):
        if tok in _NEGATIONS:
            negate = True
            continue
        if tok in _BULLISH:
            if negate:
                bearish_hits += 1
            else:
                bullish_hits += 1
            negate = False
        elif tok in _BEARISH:
            if negate:
                bullish_hits += 1
            else:
                bearish_hits += 1
            negate = False
        else:
            negate = False

    total = bullish_hits + bearish_hits
    if total == 0:
        return 0.0, "neutral"

    net = bullish_hits - bearish_hits
    score_val = net / total  # normalised to [-1, 1]

    if score_val > 0.1:
        label = "bullish"
    elif score_val < -0.1:
        label = "bearish"
    else:
        label = "neutral"

    return round(score_val, 3), label
