from pydantic import BaseModel
from typing import Optional


class NewsArticle(BaseModel):
    id: str
    title: str
    summary: Optional[str] = None
    source: str
    url: str
    published_at: Optional[str] = None
    tickers_mentioned: list[str] = []
    market: str = "all"  # "IN", "US", "all"
    category: str = "market"
    image_url: Optional[str] = None


class NewsFeedResponse(BaseModel):
    articles: list[NewsArticle]
    total: int
    has_more: bool


class NewsSource(BaseModel):
    name: str
    market: str
    status: str  # "healthy" | "down"
