from fastapi import APIRouter
from services import news_service
from services import twitter_service
from services import buzz_engine

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
