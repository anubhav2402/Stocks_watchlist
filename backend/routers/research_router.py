import asyncio
from fastapi import APIRouter
from services import research_service, research_analysis_service

router = APIRouter(tags=["research"])


@router.get("/research/fundamentals/{symbol}")
async def get_research_fundamentals(symbol: str):
    """Fetch comprehensive financial fundamentals + technicals + activity feeds."""
    return await research_service.fetch_research_fundamentals(symbol.upper())


@router.post("/research/analysis/{symbol}")
async def get_research_analysis(symbol: str, body: dict, refresh: bool = False):
    """LLM-powered analysis: commentary, valuation verdict, recommendation."""
    investment_profile = body.get("investment_profile", "") if isinstance(body, dict) else ""
    return await asyncio.to_thread(
        research_analysis_service.fetch_analysis,
        symbol.upper(),
        investment_profile,
        refresh,
    )
