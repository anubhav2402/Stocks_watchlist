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
    """Temporary debug endpoint — returns raw error details."""
    import os, yfinance as yf, httpx
    out = {}
    try:
        info = yf.Ticker(symbol.upper()).info
        out["yfinance_ok"] = True
        out["trailing_pe"] = info.get("trailingPE")
        out["forward_pe"] = info.get("forwardPE")
    except Exception as e:
        out["yfinance_error"] = str(e)
    try:
        from config import FMP_API_KEY
        out["fmp_key_set"] = bool(FMP_API_KEY)
        if FMP_API_KEY:
            r = httpx.get(
                f"https://financialmodelingprep.com/api/v3/earning_call_transcript/{symbol.upper()}?limit=1&apikey={FMP_API_KEY}",
                timeout=10,
            )
            out["fmp_status"] = r.status_code
            out["fmp_has_data"] = bool(r.json())
    except Exception as e:
        out["fmp_error"] = str(e)
    out["anthropic_key_set"] = bool(os.getenv("ANTHROPIC_API_KEY"))
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
