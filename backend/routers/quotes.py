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
