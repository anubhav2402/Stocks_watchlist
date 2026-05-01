import asyncio

from fastapi import APIRouter, HTTPException, Query
from services.yahoo_service import fetch_quote, fetch_quotes_batch, fetch_catalyst
from services import valuation_service
from models.stock import QuoteResponse, BatchQuoteResponse, CatalystResponse, ValuationResponse

router = APIRouter(tags=["quotes"])


@router.get("/quote/{symbol}", response_model=QuoteResponse)
async def get_quote(symbol: str):
    result = await fetch_quote(symbol)
    if result.error and result.price is None:
        raise HTTPException(status_code=404, detail=result.error)
    return result


@router.get("/catalysts/{symbol}", response_model=CatalystResponse)
async def get_catalyst(symbol: str):
    return await fetch_catalyst(symbol)


@router.get("/valuation/{symbol}/debug")
async def get_valuation_debug(symbol: str):
    """Debug endpoint — traces each step of valuation."""
    import os, traceback
    out = {"symbol": symbol.upper()}
    try:
        from services.valuation_service import _fetch_metrics_sync, _fetch_news_commentary_sync, _call_llm
        metrics = await asyncio.to_thread(_fetch_metrics_sync, symbol.upper())
        out["metrics_ok"] = True
        out["trailing_pe"] = metrics.get("trailing_pe")
        out["forward_pe"] = metrics.get("forward_pe")
    except Exception as e:
        out["metrics_error"] = str(e)
        return out
    try:
        transcript, quarter = await asyncio.to_thread(_fetch_news_commentary_sync, symbol.upper())
        out["news_ok"] = True
        out["news_lines"] = len(transcript.splitlines()) if transcript else 0
        out["quarter"] = quarter
    except Exception as e:
        out["news_error"] = str(e)
    try:
        out["anthropic_key_set"] = bool(os.getenv("ANTHROPIC_API_KEY"))
        # Call LLM directly with exception capture (bypasses the try/except in _call_llm)
        import os as _os
        import anthropic as _anthropic
        from services.valuation_service import _format_metrics_text, _SYSTEM_PROMPT
        _client = _anthropic.Anthropic(api_key=_os.getenv("ANTHROPIC_API_KEY"))
        _user_msg = f"Ticker: {symbol.upper()}\n\nFinancial Metrics:\n{_format_metrics_text(metrics)}"
        _resp = _client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _user_msg}],
        )
        _raw = _resp.content[0].text.strip()
        out["llm_raw"] = _raw[:500]
        out["llm_ok"] = True
    except Exception as e:
        out["llm_error"] = traceback.format_exc()
    return out


@router.get("/valuation/{symbol}", response_model=ValuationResponse)
async def get_valuation(symbol: str, refresh: bool = False):
    result = await asyncio.to_thread(
        valuation_service.fetch_valuation, symbol.upper(), refresh
    )
    if result is None:
        raise HTTPException(status_code=503, detail="Valuation unavailable")
    return result


@router.get("/quotes", response_model=BatchQuoteResponse)
async def get_quotes(symbols: str = Query(..., description="Comma-separated tickers")):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not syms:
        raise HTTPException(status_code=400, detail="No symbols provided")
    if len(syms) > 50:
        raise HTTPException(status_code=400, detail="Max 50 symbols per request")
    results = await fetch_quotes_batch(syms)
    return BatchQuoteResponse(results=results, total=len(results))
