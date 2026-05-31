from fastapi import APIRouter
from services import news_service
from services import twitter_service
from services import buzz_engine
from config import TWITTER_COOKIES_FILE, TWITTER_COOKIES_B64, DISCOVERY_WINDOW_HOURS

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    alerts = buzz_engine.get_active_alerts()
    accounts = twitter_service.list_accounts()
    news_status = news_service.get_status()
    return {
        "status": "ok",
        "twitter": {
            "enabled": twitter_service._twitter_enabled,
            "accounts_tracked": len(accounts),
            "accounts_enabled": sum(1 for a in accounts if a.enabled),
        },
        "buzz": {
            "active_alerts": len(alerts),
        },
        "news": news_status,
    }


@router.get("/health/twitter-debug")
async def twitter_debug():
    """Force a fresh auth attempt and return the result."""
    import traceback
    twitter_service._client = None
    twitter_service._twitter_enabled = True

    cookies_file_exists = TWITTER_COOKIES_FILE.exists()
    cookies_env_set = bool(TWITTER_COOKIES_B64)
    cookies_file_size = TWITTER_COOKIES_FILE.stat().st_size if cookies_file_exists else 0

    error = None
    try:
        client = await twitter_service.get_client()
        success = client is not None
    except Exception as e:
        success = False
        error = traceback.format_exc()

    return {
        "cookies_env_set": cookies_env_set,
        "cookies_file_exists": cookies_file_exists,
        "cookies_file_bytes": cookies_file_size,
        "auth_success": success,
        "twitter_enabled": twitter_service._twitter_enabled,
        "error": error,
        "last_auth_error": twitter_service._last_auth_error,
    }


@router.get("/health/scrape-debug")
async def scrape_debug():
    """Run a one-off diagnostic scrape and return per-account detail (no ingestion)."""
    results = await twitter_service.scrape_debug()
    total_tweets = sum(r.get("tweets_fetched", 0) for r in results if isinstance(r, dict))
    total_tickers = sum(r.get("tweets_with_tickers", 0) for r in results if isinstance(r, dict))
    errors = [r.get("username", "?") for r in results if isinstance(r, dict) and r.get("error")]
    return {
        "accounts_checked": len(results),
        "total_tweets_fetched": total_tweets,
        "total_tweets_with_tickers": total_tickers,
        "accounts_with_errors": errors,
        "discovery_window_hours": DISCOVERY_WINDOW_HOURS,
        "per_account": results,
    }
