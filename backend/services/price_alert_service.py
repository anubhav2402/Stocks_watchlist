"""
Daily alert jobs — run at 08:00 IST (02:30 UTC).

  1. Portfolio digest  — all tickers in any list whose name contains "us portfolio"
                         sent as a daily move summary regardless of size.
  2. High-beta alert   — tickers in any list whose name contains "high beta",
                         "software", or "saas", filtered to ≥5% daily movers only.
"""
import json
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
    price_map: dict[str, object] = {q.ticker: q for q in quotes if q and q.ticker}

    # ── Alert 1: Portfolio digest ──────────────────────────────────────────────
    if portfolio_tickers:
        rows = []
        for t in portfolio_tickers:
            q = price_map.get(t)
            rows.append({
                "ticker":   t,
                "price":    q.price if q else None,
                "change":   q.day_change if q else None,
                "pct":      q.day_change_pct if q else None,
            })
        if rows:
            html = build_portfolio_digest_email(rows)
            send_alert_email(
                user.email,
                "StockPulse · Daily Portfolio Digest",
                html,
            )

    # ── Alert 2: High-beta big movers ──────────────────────────────────────────
    if highbeta_tickers:
        movers = []
        for t in highbeta_tickers:
            q = price_map.get(t)
            if not q:
                continue
            pct = q.day_change_pct
            if pct is not None and abs(pct) >= ALERT_DAILY_MOVE_THRESHOLD:
                movers.append({
                    "ticker": t,
                    "price":  q.price,
                    "change": q.day_change,
                    "pct":    pct,
                })
        if movers:
            movers.sort(key=lambda x: abs(x["pct"]), reverse=True)
            html = build_high_beta_email(movers)
            send_alert_email(
                user.email,
                f"StockPulse · High-Beta Movers: {', '.join(m['ticker'] for m in movers[:3])}"
                + (" +more" if len(movers) > 3 else ""),
                html,
            )
