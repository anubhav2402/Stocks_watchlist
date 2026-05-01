from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Optional
from services import buzz_engine, twitter_service
from models.alert import AlertsResponse, BuzzAlert

router = APIRouter(tags=["alerts"])


@router.get("/alerts", response_model=AlertsResponse)
async def get_alerts(active_only: bool = True):
    """Return buzz alerts.  active_only=true (default) filters to open alerts."""
    alerts = buzz_engine.get_active_alerts()
    if not active_only:
        # include inactive ones from alert store
        all_alerts = list(buzz_engine._active_alerts.values())
        return AlertsResponse(alerts=all_alerts, total=len(all_alerts))
    return AlertsResponse(alerts=alerts, total=len(alerts))


@router.get("/alerts/{ticker}", response_model=BuzzAlert)
async def get_alert(ticker: str):
    alert = buzz_engine.get_alert_for_ticker(ticker.upper())
    if not alert:
        raise HTTPException(status_code=404, detail=f"No buzz alert for {ticker}")
    return alert


@router.delete("/alerts/{ticker}")
async def dismiss_alert(ticker: str):
    ok = buzz_engine.dismiss_alert(ticker.upper())
    if not ok:
        raise HTTPException(status_code=404, detail=f"No alert for {ticker}")
    return {"status": "dismissed", "ticker": ticker.upper()}


@router.post("/alerts/scrape")
async def trigger_scrape(background_tasks: BackgroundTasks):
    """Manually trigger a Twitter scrape cycle."""
    background_tasks.add_task(twitter_service.scrape_all_accounts)
    return {"status": "scrape queued"}


@router.post("/alerts/reset")
async def reset_alerts():
    """Clear all buzz state so next scrape re-scores everything fresh."""
    buzz_engine.reset_state()
    return {"status": "reset"}


@router.get("/alerts/debug/mentions")
async def debug_mentions():
    """Raw mention log — for debugging only."""
    return buzz_engine.mention_log_snapshot()
