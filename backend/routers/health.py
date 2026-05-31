from fastapi import APIRouter
from services import news_service
from services import twitter_service
from services import buzz_engine
from config import TWITTER_COOKIES_FILE, TWITTER_COOKIES_B64

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
    }
