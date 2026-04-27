from pydantic import BaseModel
from typing import Optional


class QuoteResponse(BaseModel):
    ticker: str
    name: str
    price: Optional[float] = None
    prev_close: Optional[float] = None
    day_change: Optional[float] = None
    day_change_pct: Optional[float] = None
    currency: str = "USD"
    market_cap: Optional[float] = None
    pe: Optional[float] = None
    forward_pe: Optional[float] = None
    pb: Optional[float] = None
    gross_margin: Optional[float] = None
    return_6m: Optional[float] = None
    return_1y: Optional[float] = None
    return_5y: Optional[float] = None
    sparkline: list[float] = []
    error: Optional[str] = None


class BatchQuoteResponse(BaseModel):
    results: list[QuoteResponse]
    total: int
