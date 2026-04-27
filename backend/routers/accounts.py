from fastapi import APIRouter, HTTPException
from services import twitter_service
from models.alert import TrackedAccount, AccountsResponse

router = APIRouter(tags=["accounts"])


@router.get("/accounts", response_model=AccountsResponse)
async def list_accounts():
    accounts = twitter_service.list_accounts()
    return AccountsResponse(accounts=accounts, total=len(accounts))


@router.post("/accounts", response_model=TrackedAccount, status_code=201)
async def add_account(account: TrackedAccount):
    try:
        return twitter_service.add_account(account)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.patch("/accounts/{username}/enable")
async def enable_account(username: str):
    acc = twitter_service.toggle_account(username, enabled=True)
    if not acc:
        raise HTTPException(status_code=404, detail=f"@{username} not found")
    return {"status": "enabled", "account": acc}


@router.patch("/accounts/{username}/disable")
async def disable_account(username: str):
    acc = twitter_service.toggle_account(username, enabled=False)
    if not acc:
        raise HTTPException(status_code=404, detail=f"@{username} not found")
    return {"status": "disabled", "account": acc}


@router.delete("/accounts/{username}")
async def remove_account(username: str):
    ok = twitter_service.remove_account(username)
    if not ok:
        raise HTTPException(status_code=404, detail=f"@{username} not found")
    return {"status": "removed", "username": username}
