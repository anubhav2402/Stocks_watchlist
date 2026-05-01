"""
LLM-based sentiment scoring for tweet text using Claude Haiku.
Falls back to keyword scoring if ANTHROPIC_API_KEY is not set or the API call fails.

Returns a score in [-1.0, 1.0] and a label: "bullish" | "bearish" | "neutral".
"""

import json
import os
import re
import logging
from config import DATA_DIR

logger = logging.getLogger(__name__)

# ── Keyword fallback ───────────────────────────────────────────────────────────

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
_NEGATIONS = {"not", "no", "never", "don't", "doesn't", "didn't", "won't",
              "isn't", "aren't", "wasn't", "weren't", "nor", "neither"}


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b[\w']+\b", text.lower())


def _keyword_score(text: str) -> tuple[float, str]:
    tokens = _tokenize(text)
    bullish_hits = 0
    bearish_hits = 0
    negate = False
    phrase_text = text.lower()

    for kw in _BULLISH:
        if " " in kw:
            bullish_hits += phrase_text.count(kw)
    for kw in _BEARISH:
        if " " in kw:
            bearish_hits += phrase_text.count(kw)

    for tok in tokens:
        if tok in _NEGATIONS:
            negate = True
            continue
        if tok in _BULLISH:
            bearish_hits += 1 if negate else 0
            bullish_hits += 0 if negate else 1
            negate = False
        elif tok in _BEARISH:
            bullish_hits += 1 if negate else 0
            bearish_hits += 0 if negate else 1
            negate = False
        else:
            negate = False

    total = bullish_hits + bearish_hits
    if total == 0:
        return 0.0, "neutral"

    net = bullish_hits - bearish_hits
    score_val = net / total
    label = "bullish" if score_val > 0.1 else "bearish" if score_val < -0.1 else "neutral"
    return round(score_val, 3), label


# ── LLM scoring ───────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a financial sentiment analyzer for stock market tweets.

Determine the AUTHOR'S sentiment toward the stock(s) mentioned — not just the raw price action.
A tweet saying "stock is down 8% but earnings crushed it, buying more" is bullish.
A tweet saying "stock up but I'm selling, looks like a trap" is bearish.

Respond with ONLY a JSON object, no extra text:
{"label": "bullish" | "bearish" | "neutral", "score": <float -1.0 to 1.0>}

score guide: 1.0 = very bullish, -1.0 = very bearish, 0.0 = neutral\
"""

_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return None
        try:
            import anthropic
            _client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            logger.warning("anthropic package not installed — using keyword fallback")
            return None
    return _client


def score(text: str) -> tuple[float, str]:
    """
    Returns (score, label).
    Uses Claude Haiku if ANTHROPIC_API_KEY is set, otherwise falls back to keywords.
    """
    client = _get_client()
    if client is None:
        return _keyword_score(text)

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=64,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
        result = json.loads(response.content[0].text.strip())
        label = result.get("label", "neutral")
        if label not in ("bullish", "bearish", "neutral"):
            label = "neutral"
        score_val = max(-1.0, min(1.0, float(result.get("score", 0.0))))
        return round(score_val, 3), label
    except Exception as e:
        logger.warning("LLM sentiment failed, falling back to keywords: %s", e)
        return _keyword_score(text)
