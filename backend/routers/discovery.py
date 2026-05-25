from fastapi import APIRouter, BackgroundTasks
from services import buzz_engine, twitter_service
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


@router.get("/discovery/tweets")
async def get_discovery_tweets():
    """Return unique tweets within the discovery window, each with all tickers found in it."""
    tweets = buzz_engine.get_discovery_tweets()
    return {"tweets": tweets, "total": len(tweets)}


@router.post("/discovery/scrape")
async def trigger_scrape(background_tasks: BackgroundTasks):
    """Manually trigger a Twitter scrape cycle."""
    background_tasks.add_task(twitter_service.scrape_all_accounts)
    return {"status": "scrape queued"}


@router.get("/company/{symbol}", response_model=CompanyProfile)
async def get_company_profile(symbol: str):
    return await fetch_company_profile(symbol.upper())
