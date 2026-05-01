"""
Valuation analysis service.

Fetches financial metrics from yfinance + earnings call transcript from FMP,
then calls Claude Haiku to produce a score (0-10), verdict, metrics table, and summary.
Results are cached 24h in valuation_cache.
"""

import json
import logging
import os
from datetime import datetime, timezone

import requests
import yfinance as yf

from config import FMP_API_KEY
from models.stock import ValuationMetric, ValuationResponse
from services.cache_service import valuation_cache

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a financial analyst. Given a stock's current metrics and earnings call transcript excerpt, \
return a JSON valuation analysis with EXACTLY this shape (no extra keys, no markdown):
{
  "score": <float 0-10>,
  "verdict": "Undervalued" | "Fair Value" | "Overvalued",
  "metrics": [{"name": "...", "value": "...", "note": "..."}],
  "summary": "<2-3 sentence analysis>"
}

score guide: 8-10 = compelling buy, 5-7 = fairly valued, 0-4 = stretched or avoid.
Base the verdict purely on valuation relative to fundamentals, not price momentum.
Include 5-7 metrics covering valuation multiples, growth, and profitability.\
"""


def _fmt(val, fmt=".1f", suffix="", scale=1.0, na="N/A"):
    if val is None:
        return na
    try:
        return f"{float(val) * scale:{fmt}}{suffix}"
    except Exception:
        return na


def _fetch_metrics_sync(symbol: str) -> dict:
    info = yf.Ticker(symbol).info
    ev = info.get("enterpriseValue")
    rev = info.get("totalRevenue")
    ev_rev = (ev / rev) if ev and rev and rev > 0 else None

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    target = info.get("targetMeanPrice")
    upside = ((target - price) / price * 100) if target and price and price > 0 else None

    return {
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "price_to_book": info.get("priceToBook"),
        "ev_to_revenue": ev_rev,
        "gross_margin": info.get("grossMargins"),
        "operating_margin": info.get("operatingMargins"),
        "revenue_growth": info.get("revenueGrowth"),
        "earnings_growth": info.get("earningsGrowth"),
        "total_revenue": rev,
        "market_cap": info.get("marketCap"),
        "analyst_target": target,
        "analyst_upside": upside,
        "trailing_eps": info.get("trailingEps"),
        "forward_eps": info.get("forwardEps"),
    }


def _fetch_transcript_sync(symbol: str) -> tuple[str, str | None]:
    """Returns (transcript_excerpt, quarter_label). Excerpt is first 2500 chars."""
    if not FMP_API_KEY:
        return "", None
    try:
        url = (
            f"https://financialmodelingprep.com/api/v3/earning_call_transcript/{symbol}"
            f"?limit=1&apikey={FMP_API_KEY}"
        )
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not data or not isinstance(data, list):
            return "", None
        entry = data[0]
        content = entry.get("content", "")
        quarter = f"Q{entry.get('quarter', '?')} {entry.get('year', '')}"
        return content[:2500], quarter
    except Exception as e:
        logger.warning("FMP transcript fetch failed for %s: %s", symbol, e)
        return "", None


def _format_metrics_text(m: dict) -> str:
    lines = [
        f"Trailing P/E:     {_fmt(m['trailing_pe'], '.1f', 'x')}",
        f"Forward P/E:      {_fmt(m['forward_pe'], '.1f', 'x')}",
        f"Price/Book:       {_fmt(m['price_to_book'], '.2f', 'x')}",
        f"EV/Revenue:       {_fmt(m['ev_to_revenue'], '.2f', 'x')}",
        f"Gross Margin:     {_fmt(m['gross_margin'], '.1f', '%', scale=100)}",
        f"Operating Margin: {_fmt(m['operating_margin'], '.1f', '%', scale=100)}",
        f"Revenue Growth:   {_fmt(m['revenue_growth'], '.1f', '%', scale=100)}",
        f"Earnings Growth:  {_fmt(m['earnings_growth'], '.1f', '%', scale=100)}",
        f"Analyst Target:   {_fmt(m['analyst_target'], '.2f', '')} "
        f"({_fmt(m['analyst_upside'], '.1f', '% upside')})",
        f"Market Cap:       {_fmt(m['market_cap'] and m['market_cap']/1e9, '.2f', 'B')}",
    ]
    return "\n".join(lines)


def _call_llm(symbol: str, metrics: dict, transcript: str, quarter: str | None) -> dict | None:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — skipping LLM valuation")
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        transcript_section = (
            f"\nMost recent earnings call excerpt ({quarter}):\n{transcript}"
            if transcript
            else "\n(No earnings transcript available — base analysis on metrics only.)"
        )
        user_msg = (
            f"Ticker: {symbol}\n\nFinancial Metrics:\n"
            f"{_format_metrics_text(metrics)}"
            f"{transcript_section}"
        )
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        return json.loads(response.content[0].text.strip())
    except Exception as e:
        logger.warning("LLM valuation call failed for %s: %s", symbol, e)
        return None


def fetch_valuation(symbol: str, force_refresh: bool = False) -> ValuationResponse | None:
    if not force_refresh and symbol in valuation_cache:
        result = valuation_cache[symbol]
        result.cached = True
        return result

    try:
        metrics = _fetch_metrics_sync(symbol)
        transcript, quarter = _fetch_transcript_sync(symbol)
        llm_data = _call_llm(symbol, metrics, transcript, quarter)

        if llm_data is None:
            return None

        val_metrics = [
            ValuationMetric(
                name=m.get("name", ""),
                value=m.get("value", ""),
                note=m.get("note") or None,
            )
            for m in llm_data.get("metrics", [])
        ]

        result = ValuationResponse(
            ticker=symbol,
            score=max(0.0, min(10.0, float(llm_data.get("score", 5.0)))),
            verdict=llm_data.get("verdict", "Fair Value"),
            metrics=val_metrics,
            summary=llm_data.get("summary", ""),
            transcript_date=quarter,
            generated_at=datetime.now(timezone.utc).isoformat(),
            cached=False,
        )
        valuation_cache[symbol] = result
        return result

    except Exception as e:
        logger.error("fetch_valuation failed for %s: %s", symbol, e)
        return None
