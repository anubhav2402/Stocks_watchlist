"""
Buzz Engine — detects when multiple tracked accounts mention the same stock
within the configured time window (default: 24 h) and minimum account count
(default: 2).

State is persisted to data/buzz_state.json and reloaded on startup so alerts
survive service restarts and redeployments.
"""

import json
import uuid
import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Optional

from config import BUZZ_THRESHOLD, BUZZ_WINDOW_HOURS, DISCOVERY_WINDOW_HOURS, DATA_DIR
from models.alert import TweetMention, BuzzAlert

logger = logging.getLogger(__name__)

_STATE_FILE = DATA_DIR / "buzz_state.json"

# ── In-memory store ─────────────────────────────────────────────────────────────
# { ticker: [TweetMention, ...] }  — raw mention log (rolled by window)
_mention_log: dict[str, list[TweetMention]] = defaultdict(list)

# Active buzz alerts keyed by ticker
_active_alerts: dict[str, BuzzAlert] = {}

# Set of (account, tweet_id) to avoid duplicate ingestion
_seen_tweets: set[tuple[str, str]] = set()


def _load_state() -> None:
    """Load persisted mention log from disk and rebuild alerts."""
    if not _STATE_FILE.exists():
        return
    try:
        raw = json.loads(_STATE_FILE.read_text())
        for ticker, mentions_data in raw.items():
            mentions = [TweetMention(**m) for m in mentions_data]
            _mention_log[ticker] = mentions
            for m in mentions:
                _seen_tweets.add((m.account, m.tweet_id, ticker))
        # Prune expired entries and rebuild alerts
        for ticker in list(_mention_log.keys()):
            _prune_window(ticker)
            _evaluate(ticker)
        total = sum(len(v) for v in _mention_log.values())
        logger.info("Buzz state loaded: %d tickers, %d mentions", len(_mention_log), total)
    except Exception as e:
        logger.warning("Could not load buzz state: %s", e)


def persist_state() -> None:
    """Persist current mention log to disk. Called after each scrape cycle."""
    try:
        data = {
            ticker: [m.model_dump(mode="json") for m in mentions]
            for ticker, mentions in _mention_log.items()
            if mentions
        }
        _STATE_FILE.write_text(json.dumps(data, default=str))
    except Exception as e:
        logger.warning("Could not persist buzz state: %s", e)


def reset_state() -> None:
    """Clear all in-memory and persisted state so next scrape starts fresh."""
    _mention_log.clear()
    _active_alerts.clear()
    _seen_tweets.clear()
    try:
        if _STATE_FILE.exists():
            _STATE_FILE.unlink()
    except Exception as e:
        logger.warning("Could not delete buzz state file: %s", e)
    logger.info("Buzz state reset")


# ── Public API ──────────────────────────────────────────────────────────────────

def ingest_mention(ticker: str, mention: TweetMention) -> Optional[BuzzAlert]:
    """
    Add a mention and return a BuzzAlert if buzz threshold is reached,
    or update an existing alert.  Returns None if no buzz yet.
    """
    key = (mention.account, mention.tweet_id, ticker)
    if key in _seen_tweets:
        return None
    _seen_tweets.add(key)

    _mention_log[ticker].append(mention)
    _prune_window(ticker)

    return _evaluate(ticker)


def get_active_alerts() -> list[BuzzAlert]:
    """Return all currently active buzz alerts, newest first."""
    _expire_old_alerts()
    return sorted(_active_alerts.values(), key=lambda a: a.last_seen, reverse=True)


def get_alert_for_ticker(ticker: str) -> Optional[BuzzAlert]:
    return _active_alerts.get(ticker)


def dismiss_alert(ticker: str) -> bool:
    if ticker in _active_alerts:
        _active_alerts[ticker].is_active = False
        return True
    return False


def get_discovery_tickers() -> list[dict]:
    """Return ALL tickers mentioned within DISCOVERY_WINDOW_HOURS, sorted by mention count.
    Unlike get_active_alerts(), no threshold filter — every ticker is included."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=DISCOVERY_WINDOW_HOURS)
    result = []
    for ticker, mentions in _mention_log.items():
        recent = [m for m in mentions if _parse_ts(m.timestamp) >= cutoff]
        if not recent:
            continue
        seen_accounts: dict[str, bool] = {}
        for m in recent:
            seen_accounts[m.account] = True
        accounts = list(seen_accounts.keys())
        result.append({
            "ticker": ticker,
            "mention_count": len(recent),
            "unique_accounts": accounts,
            "last_seen": max(m.timestamp for m in recent),
            "first_seen": min(m.timestamp for m in recent),
            "recent_mentions": [m.model_dump(mode="json") for m in recent[-3:]],
        })
    return sorted(result, key=lambda x: x["mention_count"], reverse=True)


def mention_log_snapshot() -> dict[str, list[dict]]:
    """Debug endpoint: raw mention log."""
    return {t: [m.model_dump() for m in mentions]
            for t, mentions in _mention_log.items()}


# Load persisted state on module import
_load_state()


# ── Internal helpers ────────────────────────────────────────────────────────────

def _window_cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=BUZZ_WINDOW_HOURS)


def _prune_window(ticker: str) -> None:
    cutoff = _window_cutoff()
    _mention_log[ticker] = [
        m for m in _mention_log[ticker]
        if _parse_ts(m.timestamp) >= cutoff
    ]


def _evaluate(ticker: str) -> Optional[BuzzAlert]:
    mentions = _mention_log[ticker]
    unique_accounts = len({m.account for m in mentions})

    if unique_accounts < BUZZ_THRESHOLD:
        return None

    # Build / update alert
    avg_sentiment = sum(m.sentiment_score for m in mentions) / len(mentions)
    if avg_sentiment > 0.1:
        label = "bullish"
    elif avg_sentiment < -0.1:
        label = "bearish"
    else:
        label = "neutral"

    timestamps = [_parse_ts(m.timestamp) for m in mentions]
    first_seen = min(timestamps).isoformat()
    last_seen = max(timestamps).isoformat()

    if ticker in _active_alerts:
        alert = _active_alerts[ticker]
        alert.mentions = mentions
        alert.mention_count = len(mentions)
        alert.unique_accounts = unique_accounts
        alert.avg_sentiment = round(avg_sentiment, 3)
        alert.sentiment_label = label
        alert.first_seen = first_seen
        alert.last_seen = last_seen
        alert.is_active = True
    else:
        alert = BuzzAlert(
            id=str(uuid.uuid4()),
            ticker=ticker,
            mentions=mentions,
            mention_count=len(mentions),
            unique_accounts=unique_accounts,
            avg_sentiment=round(avg_sentiment, 3),
            sentiment_label=label,
            first_seen=first_seen,
            last_seen=last_seen,
            is_active=True,
        )
        _active_alerts[ticker] = alert
        logger.info(
            "🔔 BUZZ: %s — %d mentions from %d accounts (avg sentiment: %.2f %s)",
            ticker, len(mentions), unique_accounts, avg_sentiment, label,
        )

    return alert


def _expire_old_alerts() -> None:
    """Deactivate alerts where last mention is outside the window."""
    cutoff = _window_cutoff()
    for ticker, alert in list(_active_alerts.items()):
        if _parse_ts(alert.last_seen) < cutoff:
            alert.is_active = False


def _parse_ts(ts: str) -> datetime:
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(timezone.utc)
