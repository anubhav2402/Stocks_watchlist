"""
News aggregation service using feedparser (RSS).

Sources:
  - Moneycontrol (Indian market)
  - Economic Times Markets
  - LiveMint Markets
  - Google News Finance (India + US)
  - Reuters Business
  - Bloomberg Markets (via RSS proxy)

All articles are stored in a capped in-memory list.
"""

import asyncio
import hashlib
import logging
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import feedparser  # type: ignore

from models.news import NewsArticle
from services.cache_service import news_cache

logger = logging.getLogger(__name__)

# ── Feed registry ───────────────────────────────────────────────────────────────
_FEEDS = [
    {
        "url": "https://www.moneycontrol.com/rss/latestnews.xml",
        "source": "Moneycontrol",
        "market": "IN",
        "category": "market",
    },
    {
        "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "source": "Economic Times",
        "market": "IN",
        "category": "market",
    },
    {
        "url": "https://www.livemint.com/rss/markets",
        "source": "LiveMint",
        "market": "IN",
        "category": "market",
    },
    {
        "url": "https://news.google.com/rss/search?q=nifty+sensex+stock+market&hl=en-IN&gl=IN&ceid=IN:en",
        "source": "Google News IN",
        "market": "IN",
        "category": "market",
    },
    {
        "url": "https://news.google.com/rss/search?q=stock+market+nasdaq+sp500&hl=en-US&gl=US&ceid=US:en",
        "source": "Google News US",
        "market": "US",
        "category": "market",
    },
    {
        "url": "https://feeds.reuters.com/reuters/businessNews",
        "source": "Reuters",
        "market": "all",
        "category": "business",
    },
]

# In-memory article store (capped at 500)
_articles: list[NewsArticle] = []
_article_ids: set[str] = set()
_MAX_ARTICLES = 500

_last_refresh: float = 0.0


# ── Public API ──────────────────────────────────────────────────────────────────

async def get_news(
    market: Optional[str] = None,
    category: Optional[str] = None,
    ticker: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[NewsArticle], int]:
    """Return paginated articles, filtered by market/category/ticker."""
    if not _articles:
        await refresh_news()

    filtered = _articles
    if market and market != "all":
        filtered = [a for a in filtered if a.market in (market, "all")]
    if category:
        filtered = [a for a in filtered if a.category == category]
    if ticker:
        t = ticker.upper()
        filtered = [a for a in filtered if t in [x.upper() for x in a.tickers_mentioned]
                    or t in a.title.upper()]

    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    return filtered[start:end], total


async def refresh_news() -> int:
    """Fetch all RSS feeds and populate the in-memory store. Returns new article count."""
    global _last_refresh

    tasks = [asyncio.to_thread(_fetch_feed, feed) for feed in _FEEDS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    new_count = 0
    for result in results:
        if isinstance(result, Exception):
            continue
        for article in result:
            if article.id not in _article_ids:
                _articles.insert(0, article)
                _article_ids.add(article.id)
                new_count += 1

    # Cap store
    if len(_articles) > _MAX_ARTICLES:
        excess = _articles[_MAX_ARTICLES:]
        for a in excess:
            _article_ids.discard(a.id)
        del _articles[_MAX_ARTICLES:]

    _last_refresh = time.time()
    logger.info("News refresh done: %d new articles (%d total)", new_count, len(_articles))
    return new_count


def get_status() -> dict:
    return {
        "total_articles": len(_articles),
        "last_refresh": datetime.fromtimestamp(_last_refresh, tz=timezone.utc).isoformat()
        if _last_refresh else None,
        "feeds": len(_FEEDS),
    }


# ── Feed fetcher (sync, runs in thread) ────────────────────────────────────────

def _fetch_feed(feed_cfg: dict) -> list[NewsArticle]:
    articles: list[NewsArticle] = []
    try:
        parsed = feedparser.parse(feed_cfg["url"])
        for entry in parsed.entries[:30]:  # cap per feed
            article = _entry_to_article(entry, feed_cfg)
            if article:
                articles.append(article)
    except Exception as e:
        logger.warning("Feed fetch error [%s]: %s", feed_cfg["source"], e)
    return articles


def _entry_to_article(entry, feed_cfg: dict) -> Optional[NewsArticle]:
    try:
        title = getattr(entry, "title", "").strip()
        link = getattr(entry, "link", "").strip()
        if not title or not link:
            return None

        # Stable ID from URL
        article_id = hashlib.md5(link.encode()).hexdigest()

        # Published timestamp
        published_at: Optional[str] = None
        if hasattr(entry, "published"):
            try:
                published_at = parsedate_to_datetime(entry.published).isoformat()
            except Exception:
                published_at = entry.published

        # Summary
        summary: Optional[str] = None
        if hasattr(entry, "summary"):
            # Strip HTML tags
            import re
            summary = re.sub(r"<[^>]+>", "", entry.summary).strip()[:400] or None

        # Image
        image_url: Optional[str] = None
        if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
            image_url = entry.media_thumbnail[0].get("url")
        elif hasattr(entry, "media_content") and entry.media_content:
            image_url = entry.media_content[0].get("url")

        return NewsArticle(
            id=article_id,
            title=title,
            summary=summary,
            source=feed_cfg["source"],
            url=link,
            published_at=published_at,
            tickers_mentioned=[],   # Could run ticker extractor on title+summary
            market=feed_cfg["market"],
            category=feed_cfg["category"],
            image_url=image_url,
        )
    except Exception as e:
        logger.debug("Entry parse error: %s", e)
        return None
