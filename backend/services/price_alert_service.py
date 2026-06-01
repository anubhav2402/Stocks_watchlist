"""
Daily alert jobs — run at 08:00 IST (02:30 UTC).

  1. Portfolio digest  — all tickers in any list whose name contains "us portfolio"
                         sent as a daily move summary regardless of size.
  2. High-beta alert   — tickers in any list whose name contains "high beta",
                         "software", or "saas", filtered to ≥5% daily movers only.
"""
import json
import math
import logging

from database import SessionLocal, User, UserState
from services.yahoo_service import fetch_quotes_batch
from services.email_service import send_alert_email, build_portfolio_digest_email, build_high_beta_email
from config import ALERT_DAILY_MOVE_THRESHOLD

logger = logging.getLogger(__name__)

_PORTFOLIO_KEYWORDS = ["us portfolio"]
_HIGHBETA_KEYWORDS  = ["high beta", "software", "saas"]


def _matches(name: str, keywords: list[str]) -> bool:
    n = name.lower()
    return any(k in n for k in keywords)


# ── Composite score (mirrors frontend JS scoring) ──────────────────────────────

def _log_score(v, lo, hi):
    if v is None or v <= 0 or not math.isfinite(v):
        return None
    return max(0.0, min(100.0, (math.log(lo) - math.log(v)) / (math.log(lo) - math.log(hi)) * 100))

def _linear_score(v, lo, hi):
    if v is None or not math.isfinite(v):
        return None
    return max(0.0, min(100.0, (v - lo) / (hi - lo) * 100))

def _sigmoid_score(v, center, scale):
    if v is None or not math.isfinite(v):
        return None
    return 100 / (1 + math.exp(-(v - center) / scale))

def _exp_decay_score(v, k):
    if v is None or not math.isfinite(v) or v < 0:
        return None
    return max(0.0, 100 * math.exp(-k * v))


def compute_composite_score(q) -> float | None:
    metrics = {
        "forwardPe":      _log_score(q.forward_pe, 50, 10),
        "pegRatio":       _linear_score(q.peg_ratio, 3.0, 0.5),
        "psRatio":        _log_score(q.ps_ratio, 20, 1),
        "qtrRevenueYoy":  _sigmoid_score(q.qtr_revenue_yoy, 15, 15),
        "qtrProfitYoy":   _sigmoid_score(q.qtr_profit_yoy, 15, 18),
        "revenueCagr":    _sigmoid_score(q.revenue_cagr, 10, 8),
        "profitCagr":     _sigmoid_score(q.profit_cagr, 10, 8) if hasattr(q, 'profit_cagr') else None,
        "revEstCyGrowth": _sigmoid_score(q.rev_est_cy_growth, 12, 12),
        "revEstNyGrowth": _sigmoid_score(q.rev_est_ny_growth, 10, 10),
        "fcfYield":       _sigmoid_score(q.fcf_yield, 4, 2),
        "roe":            _sigmoid_score((q.roe or 0) * 100, 15, 8),
        "debtToEquity":   _exp_decay_score(q.debt_to_equity, 0.003),
    }
    weights = {
        "forwardPe": 2.0, "pegRatio": 1.5, "psRatio": 1.0,
        "revEstNyGrowth": 1.0, "revEstCyGrowth": 0.8,
        "qtrRevenueYoy": 0.8, "qtrProfitYoy": 0.8,
        "revenueCagr": 0.5, "profitCagr": 0.5,
        "fcfYield": 2.0, "roe": 1.5, "debtToEquity": 1.0,
    }
    total_w = total_s = 0.0
    for key, wt in weights.items():
        v = metrics.get(key)
        if v is not None:
            total_s += v * wt
            total_w += wt
    return round(total_s / total_w, 1) if total_w > 0 else None


def _quote_row(t: str, q) -> dict:
    return {
        "ticker":  t,
        "price":   q.price if q else None,
        "change":  q.day_change if q else None,
        "pct":     q.day_change_pct if q else None,
        "return1y": q.return_1y if q else None,
        "score":   compute_composite_score(q) if q else None,
    }


async def run_daily_alerts() -> None:
    if not SessionLocal:
        return
    db = SessionLocal()
    try:
        users = db.query(User).all()
        for user in users:
            try:
                await _alert_user(db, user)
            except Exception as e:
                logger.error("Daily alert failed for user %s: %s", user.id, e)
    finally:
        db.close()


async def _alert_user(db, user: User) -> None:
    row = db.query(UserState).filter(UserState.user_id == user.id).first()
    if not row or not row.state:
        return
    try:
        state = json.loads(row.state)
    except Exception:
        return

    portfolio_tickers: list[str] = []
    highbeta_tickers:  list[str] = []

    for lst in state.get("lists", []):
        name = lst.get("name", "")
        tickers = [s["ticker"] for s in lst.get("stocks", []) if s.get("ticker")]
        if _matches(name, _PORTFOLIO_KEYWORDS):
            for t in tickers:
                if t not in portfolio_tickers:
                    portfolio_tickers.append(t)
        if _matches(name, _HIGHBETA_KEYWORDS):
            for t in tickers:
                if t not in highbeta_tickers:
                    highbeta_tickers.append(t)

    all_needed = list({*portfolio_tickers, *highbeta_tickers})
    if not all_needed:
        return

    quotes = await fetch_quotes_batch(all_needed)
    price_map = {q.ticker: q for q in quotes if q and q.ticker}

    # ── Alert 1: Portfolio digest ──────────────────────────────────────────────
    if portfolio_tickers:
        rows = [_quote_row(t, price_map.get(t)) for t in portfolio_tickers]
        html = build_portfolio_digest_email(rows)
        send_alert_email(user.email, "StockPulse · Daily Portfolio Digest", html)

    # ── Alert 2: High-beta big movers ──────────────────────────────────────────
    if highbeta_tickers:
        movers = []
        for t in highbeta_tickers:
            q = price_map.get(t)
            if not q:
                continue
            pct = q.day_change_pct
            if pct is not None and abs(pct) >= ALERT_DAILY_MOVE_THRESHOLD:
                movers.append(_quote_row(t, q))
        if movers:
            movers.sort(key=lambda x: abs(x["pct"] or 0), reverse=True)
            html = build_high_beta_email(movers)
            send_alert_email(
                user.email,
                f"StockPulse · High-Beta Movers: {', '.join(m['ticker'] for m in movers[:3])}"
                + (" +more" if len(movers) > 3 else ""),
                html,
            )
