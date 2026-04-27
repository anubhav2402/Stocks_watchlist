from fastapi import APIRouter, Query, BackgroundTasks
from typing import Optional
from services import news_service
from models.news import NewsFeedResponse, NewsSource

router = APIRouter(tags=["news"])


@router.get("/news", response_model=NewsFeedResponse)
async def get_news(
    market: Optional[str] = Query(None, description="IN | US | all"),
    category: Optional[str] = Query(None),
    ticker: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    articles, total = await news_service.get_news(
        market=market,
        category=category,
        ticker=ticker,
        page=page,
        page_size=page_size,
    )
    return NewsFeedResponse(
        articles=articles,
        total=total,
        has_more=(page * page_size) < total,
    )


@router.post("/news/refresh")
async def refresh_news(background_tasks: BackgroundTasks):
    """Trigger a manual news refresh (runs in background)."""
    background_tasks.add_task(news_service.refresh_news)
    return {"status": "refresh queued"}


@router.get("/news/status")
async def news_status():
    return news_service.get_status()
