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
    return_1m: Optional[float] = None
    return_6m: Optional[float] = None
    return_1y: Optional[float] = None
    return_5y: Optional[float] = None
    total_revenue: Optional[float] = None
    quarterly_revenue: Optional[float] = None
    ps_ratio: Optional[float] = None
    peg_ratio: Optional[float] = None
    qtr_revenue_yoy: Optional[float] = None
    qtr_profit_yoy: Optional[float] = None
    revenue_cagr: Optional[float] = None
    profit_cagr: Optional[float] = None
    fcf_yield: Optional[float] = None
    sector: Optional[str] = None
    roe: Optional[float] = None
    debt_to_equity: Optional[float] = None
    sparkline: list[float] = []
    error: Optional[str] = None


class BatchQuoteResponse(BaseModel):
    results: list[QuoteResponse]
    total: int


class CatalystResponse(BaseModel):
    ticker: str
    earnings_date: Optional[str] = None
    days_to_earnings: Optional[int] = None
    ex_div_date: Optional[str] = None
    days_to_ex_div: Optional[int] = None
    next_event_label: Optional[str] = None
    next_event_days: Optional[int] = None


class CompanyProfile(BaseModel):
    ticker: str
    name: str
    description: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    website: Optional[str] = None
    employees: Optional[int] = None
    market_cap: Optional[float] = None
    revenue: Optional[float] = None
    pe: Optional[float] = None
    forward_pe: Optional[float] = None
    gross_margin: Optional[float] = None
    revenue_growth: Optional[float] = None


class ValuationMetric(BaseModel):
    name: str
    value: str
    note: Optional[str] = None


class ValuationResponse(BaseModel):
    ticker: str
    score: float
    verdict: str
    metrics: list[ValuationMetric]
    summary: str
    transcript_date: Optional[str] = None
    generated_at: str
    cached: bool = False
