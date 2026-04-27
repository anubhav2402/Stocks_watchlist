import asyncio
import time
import logging
from typing import Optional
import yfinance as yf
from services.cache_service import quote_cache
from models.stock import QuoteResponse

logger = logging.getLogger(__name__)


def _pct(new_price: float, old_price: Optional[float]) -> Optional[float]:
    if old_price is None or old_price <= 0 or new_price is None:
        return None
    return ((new_price - old_price) / old_price) * 100


def _fetch_quote_sync(symbol: str) -> QuoteResponse:
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info

        # Price
        price = (
            info.get("regularMarketPrice")
            or info.get("currentPrice")
            or info.get("previousClose")
        )

        # Day change — use absolute change field, most reliable
        day_change = info.get("regularMarketChange")
        prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")
        if day_change is not None and price is not None:
            base = price - day_change
            day_change_pct = (day_change / base * 100) if base > 0 else None
        elif prev_close and price:
            day_change = price - prev_close
            day_change_pct = _pct(price, prev_close)
        else:
            day_change = None
            day_change_pct = None

        # Fundamentals
        pe = info.get("trailingPE")
        forward_pe = info.get("forwardPE")
        pb = info.get("priceToBook")
        gross_margin = info.get("grossMargins")

        # Historical returns via fast history fetch
        hist = ticker.history(period="5y", interval="1mo")
        closes = hist["Close"].dropna().tolist() if not hist.empty else []

        def hist_return(months_ago: int) -> Optional[float]:
            idx = len(closes) - 1 - months_ago
            if idx >= 0 and closes[-1] and closes[idx]:
                return _pct(closes[-1], closes[idx])
            return None

        return_6m = hist_return(6)
        return_1y = hist_return(12)
        return_5y = hist_return(60)

        # 5-day sparkline (daily closes)
        spark_hist = ticker.history(period="5d", interval="1d")
        sparkline = spark_hist["Close"].dropna().tolist() if not spark_hist.empty else []

        return QuoteResponse(
            ticker=symbol,
            name=info.get("longName") or info.get("shortName") or symbol,
            price=price,
            prev_close=prev_close,
            day_change=day_change,
            day_change_pct=day_change_pct,
            currency=info.get("currency", "USD"),
            market_cap=info.get("marketCap"),
            pe=pe,
            forward_pe=forward_pe,
            pb=pb,
            gross_margin=gross_margin,
            return_6m=return_6m,
            return_1y=return_1y,
            return_5y=return_5y,
            sparkline=sparkline,
        )

    except Exception as e:
        logger.warning("Failed to fetch %s: %s", symbol, e)
        return QuoteResponse(ticker=symbol, name=symbol, error=str(e))


async def fetch_quote(symbol: str) -> QuoteResponse:
    symbol = symbol.upper().strip()
    if symbol in quote_cache:
        return quote_cache[symbol]
    result = await asyncio.to_thread(_fetch_quote_sync, symbol)
    quote_cache[symbol] = result
    return result


async def fetch_quotes_batch(symbols: list[str]) -> list[QuoteResponse]:
    tasks = [fetch_quote(s) for s in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            out.append(QuoteResponse(ticker=symbols[i], name=symbols[i], error=str(r)))
        else:
            out.append(r)
    return out
