import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
import yfinance as yf
from services.cache_service import quote_cache, catalyst_cache, profile_cache
from models.stock import QuoteResponse, CatalystResponse, CompanyProfile

logger = logging.getLogger(__name__)


def _pct(new_price: float, old_price: Optional[float]) -> Optional[float]:
    if old_price is None or old_price <= 0 or new_price is None:
        return None
    return ((new_price - old_price) / old_price) * 100


def _fetch_quote_sync(symbol: str) -> QuoteResponse:
    import time, random

    def _get_ticker_info():
        """Fetch yfinance Ticker info with up to 3 retries on empty/429 responses."""
        last_exc = None
        for attempt in range(3):
            try:
                t = yf.Ticker(symbol)
                i = t.info
                if i and (i.get("regularMarketPrice") or i.get("currentPrice") or i.get("previousClose")):
                    return t, i
                # Got an empty-ish dict — wait and retry
                if attempt < 2:
                    time.sleep(2 ** attempt + random.uniform(0, 1))
            except Exception as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(2 ** attempt + random.uniform(0, 1))
        if last_exc:
            raise last_exc
        return yf.Ticker(symbol), {}  # best-effort empty

    try:
        ticker, info = _get_ticker_info()

        # Price
        price = (
            info.get("regularMarketPrice")
            or info.get("currentPrice")
            or info.get("previousClose")
        )

        # Day change — prefer absolute change field; fall back to prev_close diff
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
        total_revenue = info.get("totalRevenue")
        ps_ratio = info.get("priceToSalesTrailing12Months")
        peg_ratio = info.get("trailingPegRatio") or info.get("pegRatio")
        fcf_ttm = info.get("freeCashflow")
        market_cap_raw = info.get("marketCap")
        fcf_yield = (fcf_ttm / market_cap_raw * 100) if fcf_ttm and market_cap_raw and market_cap_raw > 0 else None

        sector = info.get("sector")
        roe = info.get("returnOnEquity")
        debt_to_equity = info.get("debtToEquity")

        # Quarterly income: last Q revenue, + YOY growth vs same Q last year
        quarterly_revenue = None
        qtr_revenue_yoy = None
        qtr_profit_yoy = None
        try:
            import math
            q_inc = ticker.quarterly_income_stmt
            if q_inc is not None and not q_inc.empty:
                def _safe_float(series, col_idx):
                    try:
                        v = series.iloc[col_idx]
                        return None if (v is None or math.isnan(float(v))) else float(v)
                    except Exception:
                        return None

                def _first_valid_idx(series):
                    """Return index of the most recent non-NaN column."""
                    for i in range(len(series)):
                        v = _safe_float(series, i)
                        if v is not None:
                            return i
                    return None

                def _yoy(series):
                    """YoY growth: most recent valid quarter vs same quarter last year (+4)."""
                    cur_idx = _first_valid_idx(series)
                    if cur_idx is None:
                        return None, None
                    prior_idx = cur_idx + 4
                    if prior_idx >= len(series):
                        return None, None
                    v_cur  = _safe_float(series, cur_idx)
                    v_prev = _safe_float(series, prior_idx)
                    if v_cur is not None and v_prev is not None and v_prev != 0:
                        return v_cur, (v_cur - v_prev) / abs(v_prev) * 100
                    return v_cur, None

                rev_names = [r for r in q_inc.index if 'total revenue' in r.lower()]
                if rev_names:
                    rev_s = q_inc.loc[rev_names[0]]
                    cur_rev, qtr_revenue_yoy = _yoy(rev_s)
                    quarterly_revenue = cur_rev

                ni_names = None
                for key in ['net income common stockholders', 'net income']:
                    matches = [r for r in q_inc.index if key in r.lower()]
                    if matches:
                        ni_names = matches
                        break
                if ni_names:
                    ni_s = q_inc.loc[ni_names[0]]
                    _, qtr_profit_yoy = _yoy(ni_s)
        except Exception:
            pass

        # Annual income: revenue + profit CAGR over available history (typically 3-4 yrs)
        revenue_cagr = None
        profit_cagr = None
        try:
            import math
            ann_inc = ticker.income_stmt
            if ann_inc is not None and not ann_inc.empty and len(ann_inc.columns) >= 2:

                def _ann_val(series, col_idx):
                    try:
                        v = series.iloc[col_idx]
                        return None if (v is None or math.isnan(float(v))) else float(v)
                    except Exception:
                        return None

                def _oldest_valid(series):
                    """Return (value, col_index) for the oldest non-NaN column."""
                    for i in range(len(series) - 1, -1, -1):
                        v = _ann_val(series, i)
                        if v is not None:
                            return v, i
                    return None, None

                def _cagr(series, row_label):
                    names = [r for r in ann_inc.index if row_label in r.lower()]
                    if not names:
                        return None
                    s = ann_inc.loc[names[0]]
                    v_new = _ann_val(s, 0)
                    v_old, old_idx = _oldest_valid(s)
                    if v_new and v_old and v_new > 0 and v_old > 0 and old_idx > 0:
                        return ((v_new / v_old) ** (1 / old_idx) - 1) * 100
                    return None

                revenue_cagr = _cagr(ann_inc, 'total revenue')

                ni_label = None
                for key in ['net income common stockholders', 'net income']:
                    if any(key in r.lower() for r in ann_inc.index):
                        ni_label = key
                        break
                if ni_label:
                    profit_cagr = _cagr(ann_inc, ni_label)
        except Exception:
            pass

        # Historical returns via monthly history (fast, small payload)
        hist = ticker.history(period="5y", interval="1mo")
        closes = hist["Close"].dropna().tolist() if not hist.empty else []

        def hist_return(months_ago: int) -> Optional[float]:
            idx = len(closes) - 1 - months_ago
            if idx >= 0 and price and closes[idx]:
                return _pct(price, closes[idx])
            return None

        return_1m = hist_return(1)
        return_6m = hist_return(6)
        return_1y = hist_return(12)
        return_5y = hist_return(60)

        # 5-day sparkline (daily closes) — also final fallback for day-change
        spark_hist = ticker.history(period="5d", interval="1d")
        sparkline = spark_hist["Close"].dropna().tolist() if not spark_hist.empty else []

        # Derive day-change from sparkline if info-based values are missing
        if day_change_pct is None and len(sparkline) >= 2:
            spark_prev = sparkline[-2]
            spark_cur  = sparkline[-1]
            prev_close = prev_close or spark_prev
            price      = price      or spark_cur
            if spark_prev and spark_prev > 0:
                day_change     = spark_cur - spark_prev
                day_change_pct = (day_change / spark_prev) * 100

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
            return_1m=return_1m,
            return_6m=return_6m,
            return_1y=return_1y,
            return_5y=return_5y,
            total_revenue=total_revenue,
            quarterly_revenue=quarterly_revenue,
            ps_ratio=ps_ratio,
            peg_ratio=peg_ratio,
            qtr_revenue_yoy=qtr_revenue_yoy,
            qtr_profit_yoy=qtr_profit_yoy,
            revenue_cagr=revenue_cagr,
            profit_cagr=profit_cagr,
            fcf_yield=fcf_yield,
            sector=sector,
            roe=roe,
            debt_to_equity=debt_to_equity,
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


def _fetch_catalyst_sync(symbol: str) -> CatalystResponse:
    today = datetime.now(timezone.utc).date()
    try:
        t = yf.Ticker(symbol)
        cal = t.calendar

        earnings_date = None
        days_to_earnings = None
        ex_div_date = None
        days_to_ex_div = None

        if isinstance(cal, dict):
            # Earnings Date — may be a list of Timestamps or a single value
            ed = cal.get("Earnings Date")
            if ed is not None:
                if isinstance(ed, list):
                    ed = ed[0] if ed else None
                try:
                    import pandas as pd
                    ed_date = pd.Timestamp(ed).date()
                    if ed_date >= today:
                        earnings_date = ed_date.isoformat()
                        days_to_earnings = (ed_date - today).days
                except Exception:
                    pass

            xd = cal.get("Ex-Dividend Date")
            if xd is not None:
                try:
                    import pandas as pd
                    xd_date = pd.Timestamp(xd).date()
                    if xd_date >= today:
                        ex_div_date = xd_date.isoformat()
                        days_to_ex_div = (xd_date - today).days
                except Exception:
                    pass

        events = []
        if days_to_earnings is not None:
            events.append(("Earnings", days_to_earnings))
        if days_to_ex_div is not None:
            events.append(("Ex-Div", days_to_ex_div))
        events.sort(key=lambda x: x[1])

        return CatalystResponse(
            ticker=symbol,
            earnings_date=earnings_date,
            days_to_earnings=days_to_earnings,
            ex_div_date=ex_div_date,
            days_to_ex_div=days_to_ex_div,
            next_event_label=events[0][0] if events else None,
            next_event_days=events[0][1] if events else None,
        )
    except Exception as e:
        logger.warning("Failed to fetch catalyst for %s: %s", symbol, e)
        return CatalystResponse(ticker=symbol)


async def fetch_catalyst(symbol: str) -> CatalystResponse:
    symbol = symbol.upper().strip()
    if symbol in catalyst_cache:
        return catalyst_cache[symbol]
    result = await asyncio.to_thread(_fetch_catalyst_sync, symbol)
    catalyst_cache[symbol] = result
    return result


def _fetch_company_profile_sync(symbol: str) -> CompanyProfile:
    info = yf.Ticker(symbol).info or {}
    return CompanyProfile(
        ticker=symbol,
        name=info.get("longName") or info.get("shortName") or symbol,
        description=info.get("longBusinessSummary"),
        sector=info.get("sector"),
        industry=info.get("industry"),
        country=info.get("country"),
        website=info.get("website"),
        employees=info.get("fullTimeEmployees"),
        market_cap=info.get("marketCap"),
        revenue=info.get("totalRevenue"),
        pe=info.get("trailingPE"),
        forward_pe=info.get("forwardPE"),
        gross_margin=info.get("grossMargins"),
        revenue_growth=info.get("revenueGrowth"),
    )


async def fetch_company_profile(symbol: str) -> CompanyProfile:
    symbol = symbol.upper().strip()
    if symbol in profile_cache:
        return profile_cache[symbol]
    result = await asyncio.to_thread(_fetch_company_profile_sync, symbol)
    profile_cache[symbol] = result
    return result
