from fastapi import APIRouter
from services import research_service

router = APIRouter(tags=["research"])


@router.get("/research/fundamentals/{symbol}")
async def get_research_fundamentals(symbol: str):
    """Fetch comprehensive financial fundamentals + technicals for equity research."""
    return await research_service.fetch_research_fundamentals(symbol.upper())
