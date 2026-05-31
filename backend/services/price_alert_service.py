"""
Hourly job: check each user's watchlist for target price hits and big daily moves.
Sends one email per user per run if any alerts fire.
De-duplicates: won't re-fire the same alert within 24 hours.
"""
import json
import logging
from datetime import datetime, timedelta

from database import SessionLocal, User, UserState, SentAlert
from services.yahoo_service import fetch_quotes_batch
from services.email_service import send_alert_email, build_alert_email
from config import ALERT_DAILY_MOVE_THRESHOLD

logger = logging.getLogger(__name__)


async def check_price_alerts() -> None:
    if not SessionLocal:
        return
    db = SessionLocal()
    try:
        users = db.query(User).all()
        for user in users:
            try:
                await _check_user(db, user)
            except Exception as e:
                logger.error("Alert check failed for user %s: %s", user.id, e)
    finally:
        db.close()


async def _check_user(db, user: User) -> None:
    row = db.query(UserState).filter(UserState.user_id == user.id).first()
    if not row or not row.state:
        return

    try:
        state = json.loads(row.state)
    except Exception:
        return

    # Collect all tickers with target prices across all lists
    tickers_with_target: dict[str, float] = {}  # ticker -> targetPrice
    all_tickers: list[str] = []

    for lst in state.get("lists", []):
        for stock in lst.get("stocks", []):
            t = stock.get("ticker", "")
            if not t:
                continue
            if t not in all_tickers:
                all_tickers.append(t)
            tp = stock.get("targetPrice")
            if tp and isinstance(tp, (int, float)) and tp > 0:
                tickers_with_target[t] = float(tp)

    if not all_tickers:
        return

    quotes = await fetch_quotes_batch(all_tickers)
    price_map: dict[str, dict] = {}
    for q in quotes:
        if q and q.ticker:
            price_map[q.ticker] = {"price": q.price, "day_pct": q.day_change_pct}

    cutoff = datetime.utcnow() - timedelta(hours=24)
    recent_alerts = db.query(SentAlert).filter(
        SentAlert.user_id == user.id,
        SentAlert.sent_at >= cutoff,
    ).all()
    sent_keys = {(a.ticker, a.alert_type) for a in recent_alerts}

    triggered = []

    for ticker, data in price_map.items():
        price = data.get("price")
        day_pct = data.get("day_pct")

        # Target price alert
        if ticker in tickers_with_target and price is not None:
            target = tickers_with_target[ticker]
            key = (ticker, "target_hit")
            if key not in sent_keys and price >= target:
                triggered.append({
                    "ticker": ticker,
                    "type": "target_hit",
                    "message": f"Hit your target of ${target:,.2f}",
                    "detail": f"Current: ${price:,.2f}",
                    "price": price,
                })
                sent_keys.add(key)

        # Big daily move alert
        if day_pct is not None and abs(day_pct) >= ALERT_DAILY_MOVE_THRESHOLD:
            key = (ticker, "big_move")
            if key not in sent_keys:
                direction = "▲" if day_pct > 0 else "▼"
                triggered.append({
                    "ticker": ticker,
                    "type": "big_move",
                    "message": f"Big move today",
                    "detail": f"{direction} {day_pct:+.2f}% · ${price:,.2f}" if price else f"{direction} {day_pct:+.2f}%",
                    "price": price,
                })
                sent_keys.add(key)

    if not triggered:
        return

    html = build_alert_email(triggered)
    subject = f"StockPulse: {len(triggered)} alert{'s' if len(triggered) > 1 else ''} — " + \
              ", ".join(a["ticker"] for a in triggered[:3]) + \
              (" +more" if len(triggered) > 3 else "")

    sent = send_alert_email(user.email, subject, html)
    if sent:
        for a in triggered:
            db.add(SentAlert(
                user_id=user.id,
                ticker=a["ticker"],
                alert_type=a["type"],
                price_at_send=a["price"],
            ))
        db.commit()
