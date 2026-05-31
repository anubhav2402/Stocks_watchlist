"""
APScheduler background jobs.

Jobs registered:
  - scrape_twitter    every SCRAPE_INTERVAL_MINUTES (default 30 min)
  - refresh_news      every NEWS_INTERVAL_MINUTES   (default 15 min)

The scheduler is started inside main.py's lifespan handler so it shares
the same process as FastAPI (no separate worker needed for v1).
"""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore

from config import SCRAPE_INTERVAL_MINUTES, NEWS_INTERVAL_MINUTES, ALERT_CHECK_INTERVAL_MINUTES

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")


def _register_jobs() -> None:
    from services import twitter_service, news_service, price_alert_service

    scheduler.add_job(
        twitter_service.scrape_all_accounts,
        trigger="interval",
        minutes=SCRAPE_INTERVAL_MINUTES,
        id="scrape_twitter",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        news_service.refresh_news,
        trigger="interval",
        minutes=NEWS_INTERVAL_MINUTES,
        id="refresh_news",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        price_alert_service.check_price_alerts,
        trigger="interval",
        minutes=ALERT_CHECK_INTERVAL_MINUTES,
        id="price_alerts",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    logger.info(
        "Scheduler jobs registered: twitter every %d min, news every %d min, alerts every %d min",
        SCRAPE_INTERVAL_MINUTES,
        NEWS_INTERVAL_MINUTES,
        ALERT_CHECK_INTERVAL_MINUTES,
    )


async def startup() -> None:
    """Called by FastAPI lifespan on startup."""
    _register_jobs()
    scheduler.start()
    logger.info("APScheduler started")

    # Run initial data loads immediately (don't wait for first interval)
    from services import news_service, twitter_service
    asyncio.create_task(news_service.refresh_news())
    asyncio.create_task(twitter_service.scrape_all_accounts())


async def shutdown() -> None:
    """Called by FastAPI lifespan on shutdown."""
    scheduler.shutdown(wait=False)
    logger.info("APScheduler stopped")
