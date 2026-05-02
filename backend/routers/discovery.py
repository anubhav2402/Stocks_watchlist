from fastapi import APIRouter
from services import buzz_engine
from services.yahoo_service import fetch_company_profile
from models.stock import CompanyProfile
from config import DISCOVERY_WINDOW_HOURS

router = APIRouter(tags=["discovery"])


@router.get("/discovery")
async def get_discovery():
    """Return all tickers mentioned by tracked accounts within the discovery window."""
    tickers = buzz_engine.get_discovery_tickers()
    return {
        "tickers": tickers,
        "total": len(tickers),
        "window_hours": DISCOVERY_WINDOW_HOURS,
    }


@router.get("/company/{symbol}", response_model=CompanyProfile)
async def get_company_profile(symbol: str):
    return await fetch_company_profile(symbol.upper())
