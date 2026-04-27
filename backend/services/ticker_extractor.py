"""
Extracts stock ticker symbols from tweet text.

Priority order:
  1. Cashtags:  $AAPL, $RELIANCE, $TCS
  2. Alias map: company name → ticker (e.g. "Infosys" → "INFY.NS")
  3. Standalone uppercase tokens: AAPL, TCS, NVDA (3-6 chars, filtered)

Indian stocks are returned with .NS suffix; US stocks without suffix.
"""

import re
import json
import logging
from pathlib import Path
from config import DATA_DIR

logger = logging.getLogger(__name__)

# ── Load alias map ──────────────────────────────────────────────────────────────
def _load_aliases() -> dict[str, str | None]:
    path = DATA_DIR / "ticker_aliases.json"
    try:
        return json.loads(path.read_text())
    except Exception as e:
        logger.warning("Could not load ticker_aliases.json: %s", e)
        return {}


_ALIASES: dict[str, str | None] = _load_aliases()

# Build a sorted list of multi-word aliases (longest first to avoid partial matches)
_ALIAS_PHRASES: list[tuple[str, str | None]] = sorted(
    ((k.lower(), v) for k, v in _ALIASES.items() if " " in k),
    key=lambda x: -len(x[0]),
)

# Single-word aliases
_ALIAS_WORDS: dict[str, str | None] = {
    k.lower(): v for k, v in _ALIASES.items() if " " not in k
}

# Tokens to explicitly ignore (common words that look like tickers)
_STOPWORDS = {
    "CEO", "CFO", "COO", "CTO", "IPO", "AGM", "EGM", "BSE", "NSE", "NYSE",
    "SEBI", "RBI", "FII", "DII", "FPI", "MF", "NAV", "ETF", "GDP", "CPI",
    "US", "UK", "EU", "UAE", "USA", "NRI", "NRI", "EOD", "EOW", "Q1", "Q2",
    "Q3", "Q4", "FY", "YOY", "QOQ", "MOM", "ATH", "PE", "PB", "EPS", "ROE",
    "ROI", "PAT", "EBIT", "EBITDA", "CAGR", "BUY", "SELL", "HOLD", "SL",
    "TP", "TGT", "CMP", "LTP", "MCX", "NCDEX", "SGB", "DRHP", "OFS",
    "NFO", "SIP", "MFD", "AMC", "DIV", "BONUS", "SPLIT", "LTP", "ASM",
    "GSM", "PWM", "IOB", "BOB", "OBC", "UCO", "CBI", "BOM", "NSE", "BSE",
}

# Valid known NSE symbols (a small hardcoded fast-check set + .NS suffix rule)
_CASHTAG_RE = re.compile(r"\$([A-Z][A-Z0-9\-\.]{1,9})", re.IGNORECASE)
_UPPER_TOKEN_RE = re.compile(r"\b([A-Z][A-Z0-9]{2,8})\b")


def extract_tickers(text: str) -> list[str]:
    """Return deduplicated list of ticker symbols found in *text*."""
    found: list[str] = []
    seen: set[str] = set()

    def _add(ticker: str | None) -> None:
        if ticker and ticker not in seen:
            seen.add(ticker)
            found.append(ticker)

    # 1. Cashtags — most reliable signal
    for m in _CASHTAG_RE.finditer(text):
        raw = m.group(1).upper()
        # Map via alias (handles $RELIANCE → RELIANCE.NS)
        resolved = _ALIAS_WORDS.get(raw.lower()) or _ALIAS_WORDS.get(raw)
        _add(resolved or raw)

    # 2. Multi-word alias phrases
    lower_text = text.lower()
    for phrase, ticker in _ALIAS_PHRASES:
        if phrase in lower_text:
            _add(ticker)

    # 3. Single-word aliases (case-insensitive word boundaries)
    for token in re.findall(r"\b\w[\w&\.]+\b", lower_text):
        if token in _ALIAS_WORDS:
            _add(_ALIAS_WORDS[token])

    # 4. Standalone uppercase tokens (loose heuristic, low-confidence)
    for m in _UPPER_TOKEN_RE.finditer(text):
        tok = m.group(1)
        if tok in _STOPWORDS:
            continue
        if tok in seen:
            continue
        # Accept only if it maps to a known alias or looks like a known NSE pattern
        resolved = _ALIAS_WORDS.get(tok.lower())
        if resolved is not None:
            _add(resolved)
        # Otherwise skip — too many false positives without a full symbol list

    return found
