"""
Twitter / X scraping service using twikit.

Authentication flow:
  1. Try to load saved cookies from TWITTER_COOKIES_FILE
  2. If no cookies, login with username/email/password, then save cookies
  3. For each tracked account, fetch their recent tweets
  4. Extract tickers + sentiment, feed into buzz engine

This module exposes:
  - scrape_all_accounts()  — called by the APScheduler job
  - get_client()           — shared twikit Client instance
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import (
    TWITTER_USERNAME, TWITTER_EMAIL, TWITTER_PASSWORD,
    TWITTER_COOKIES_FILE, DATA_DIR,
)
from services.ticker_extractor import extract_tickers
from services.sentiment_service import score as sentiment_score
from services import buzz_engine
from models.alert import TweetMention, TrackedAccount

logger = logging.getLogger(__name__)


def _apply_twikit_patches():
    """
    Monkey-patch twikit 1.7.6 User class to handle optional/missing fields.
    Fixes KeyErrors for: 'urls', 'pinned_tweet_ids_str', 'withheld_in_countries'.
    More reliable than file-patching since it works regardless of .pyc cache.
    """
    try:
        import twikit.user as _tu
        _orig_init = _tu.User.__init__

        def _safe_init(self, client, data):
            # Defensively fill in optional legacy fields before twikit reads them
            try:
                legacy = data.get('legacy') if isinstance(data, dict) else None
                if isinstance(legacy, dict):
                    desc = legacy.get('entities', {}).get('description', {})
                    if isinstance(desc, dict) and 'urls' not in desc:
                        desc['urls'] = []
                    legacy.setdefault('pinned_tweet_ids_str', [])
                    legacy.setdefault('withheld_in_countries', [])
            except Exception:
                pass
            _orig_init(self, client, data)

        _tu.User.__init__ = _safe_init
        logger.info("twikit User.__init__ patched successfully")
    except Exception as e:
        logger.warning("twikit monkey-patch failed (non-fatal): %s", e)


_apply_twikit_patches()

# ── twikit client singleton ─────────────────────────────────────────────────────
_client: Optional[object] = None   # twikit.Client
_twitter_enabled: bool = True


def _load_accounts() -> list[TrackedAccount]:
    path = DATA_DIR / "tracked_accounts.json"
    try:
        raw = json.loads(path.read_text())
        return [TrackedAccount(**a) for a in raw]
    except Exception as e:
        logger.warning("Could not load tracked_accounts.json: %s", e)
        return []


# Runtime mutable account list (supports add/remove via API)
_accounts: list[TrackedAccount] = _load_accounts()


def _get_client_sync():
    """Create and return an authenticated twikit Client (synchronous)."""
    global _client, _twitter_enabled

    if _client is not None:
        return _client

    try:
        from twikit import Client  # type: ignore
        client = Client("en-US")

        if TWITTER_COOKIES_FILE.exists():
            client.load_cookies(str(TWITTER_COOKIES_FILE))
            logger.info("Loaded Twitter cookies from %s", TWITTER_COOKIES_FILE)
            _client = client
            return _client

        if not TWITTER_USERNAME or not TWITTER_PASSWORD:
            raise ValueError("Twitter credentials not set")

        logger.info("Logging in to Twitter as %s …", TWITTER_USERNAME)
        client.login(
            auth_info_1=TWITTER_USERNAME,
            auth_info_2=TWITTER_EMAIL or None,
            password=TWITTER_PASSWORD,
        )
        client.save_cookies(str(TWITTER_COOKIES_FILE))
        logger.info("Twitter login successful — cookies saved")
        _client = client
        return _client

    except ImportError:
        logger.error("twikit not installed — run: pip install twikit")
        _twitter_enabled = False
        return None
    except Exception as e:
        logger.error("Twitter auth failed: %s", e)
        _twitter_enabled = False
        return None


async def get_client():
    """Return authenticated twikit Client (async wrapper — runs init in thread)."""
    global _twitter_enabled
    if not _twitter_enabled:
        return None
    if _client is not None:
        return _client
    return await asyncio.to_thread(_get_client_sync)


def _scrape_account_sync(client, account: TrackedAccount) -> int:
    """Fetch recent tweets for one account (synchronous — runs in thread pool)."""
    if not account.enabled:
        return 0
    count = 0
    try:
        user = client.get_user_by_screen_name(account.username)
        tweets = user.get_tweets("Tweets", count=20)
        if not tweets:
            return 0

        for tweet in tweets:
            # full_text has the complete note-tweet text; text may be truncated
            full = getattr(tweet, 'full_text', None) or tweet.text
            tickers = extract_tickers(full)
            if not tickers:
                continue

            ts = _tweet_timestamp(tweet)
            s_score, s_label = sentiment_score(full)
            tweet_url = f"https://x.com/{account.username}/status/{tweet.id}"

            for ticker in tickers:
                mention = TweetMention(
                    tweet_id=str(tweet.id),
                    account=account.username,
                    text=full,
                    timestamp=ts,
                    sentiment_score=s_score,
                    sentiment_label=s_label,
                    url=tweet_url,
                )
                result = buzz_engine.ingest_mention(ticker, mention)
                if result:
                    logger.info("Buzz detected for %s via @%s", ticker, account.username)
                count += 1

        account.last_scraped = datetime.now(timezone.utc).isoformat()
        account.tweets_scraped += len(tweets)

    except Exception as e:
        logger.warning("Failed to scrape @%s: %s", account.username, e)

    return count


async def _scrape_account(client, account: TrackedAccount) -> int:
    """Async wrapper — runs sync scrape in thread so it doesn't block the event loop."""
    return await asyncio.to_thread(_scrape_account_sync, client, account)


def _tweet_timestamp(tweet) -> str:
    """Extract ISO timestamp from twikit Tweet object."""
    try:
        if hasattr(tweet, "created_at_datetime") and tweet.created_at_datetime:
            dt = tweet.created_at_datetime
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        if hasattr(tweet, "created_at") and tweet.created_at:
            # twikit returns Twitter date string: "Mon Jan 01 00:00:00 +0000 2024"
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(tweet.created_at).isoformat()
    except Exception:
        pass
    return datetime.now(timezone.utc).isoformat()


async def scrape_all_accounts() -> dict:
    """Main entry point called by the scheduler."""
    client = await get_client()
    if client is None:
        return {"status": "disabled", "accounts_scraped": 0, "mentions": 0}

    enabled = [a for a in _accounts if a.enabled]
    logger.info("Scraping %d Twitter accounts …", len(enabled))

    tasks = [_scrape_account(client, acc) for acc in enabled]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    total_mentions = sum(r for r in results if isinstance(r, int))
    errors = sum(1 for r in results if isinstance(r, Exception))

    logger.info(
        "Twitter scrape done: %d accounts, %d mentions, %d errors",
        len(enabled), total_mentions, errors,
    )
    buzz_engine.persist_state()
    return {
        "status": "ok",
        "accounts_scraped": len(enabled),
        "mentions": total_mentions,
        "errors": errors,
    }


# ── Account management (used by /api/accounts router) ──────────────────────────

def list_accounts() -> list[TrackedAccount]:
    return _accounts


def add_account(account: TrackedAccount) -> TrackedAccount:
    # Check for duplicate
    if any(a.username.lower() == account.username.lower() for a in _accounts):
        raise ValueError(f"Account @{account.username} already tracked")
    _accounts.append(account)
    _persist_accounts()
    return account


def toggle_account(username: str, enabled: bool) -> Optional[TrackedAccount]:
    for acc in _accounts:
        if acc.username.lower() == username.lower():
            acc.enabled = enabled
            _persist_accounts()
            return acc
    return None


def remove_account(username: str) -> bool:
    global _accounts
    before = len(_accounts)
    _accounts = [a for a in _accounts if a.username.lower() != username.lower()]
    if len(_accounts) < before:
        _persist_accounts()
        return True
    return False


def _persist_accounts() -> None:
    path = DATA_DIR / "tracked_accounts.json"
    try:
        path.write_text(json.dumps([a.model_dump() for a in _accounts], indent=2))
    except Exception as e:
        logger.warning("Could not persist accounts: %s", e)
