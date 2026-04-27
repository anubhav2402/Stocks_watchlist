from pydantic import BaseModel
from typing import Optional


class TweetMention(BaseModel):
    tweet_id: str
    account: str
    text: str
    timestamp: str          # ISO-8601
    sentiment_score: float  # -1.0 to 1.0
    sentiment_label: str    # "bullish" | "bearish" | "neutral"
    url: str = ""


class BuzzAlert(BaseModel):
    id: str
    ticker: str
    name: Optional[str] = None
    mentions: list[TweetMention] = []
    mention_count: int = 0
    unique_accounts: int = 0
    avg_sentiment: float = 0.0
    sentiment_label: str = "neutral"
    first_seen: str
    last_seen: str
    is_active: bool = True


class AlertsResponse(BaseModel):
    alerts: list[BuzzAlert]
    total: int


class TrackedAccount(BaseModel):
    username: str
    display_name: str
    category: str   # "operator" | "analyst" | "fund" | "news" | "exchange" | "regulator"
    market: str     # "IN" | "US" | "all"
    enabled: bool = True
    last_scraped: Optional[str] = None
    tweets_scraped: int = 0


class AccountsResponse(BaseModel):
    accounts: list[TrackedAccount]
    total: int
