import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel
from jose import jwt, JWTError

from database import get_db, User, UserState
from services.email_service import send_alert_email, build_portfolio_digest_email

router = APIRouter(tags=["sync"])

SECRET = os.getenv("JWT_SECRET", "change-this-secret-in-production")
ALGO = "HS256"


def current_user_id(authorization: str = Header(None)) -> int:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(authorization[7:], SECRET, algorithms=[ALGO])
        return int(payload["sub"])
    except JWTError:
        raise HTTPException(401, "Invalid or expired token")


class StateBody(BaseModel):
    state: str


@router.get("/sync/state")
def get_state(user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    if db is None:
        return {"state": None}
    row = db.query(UserState).filter(UserState.user_id == user_id).first()
    return {"state": row.state if row else None}


@router.post("/sync/test-alert")
def test_alert(user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    if db is None:
        raise HTTPException(503, "Database not configured")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    sample = [
        {"ticker": "NVDA", "price": 1089.50, "change": 42.10, "pct": 4.02},
        {"ticker": "AAPL", "price": 198.45,  "change": -3.20, "pct": -1.59},
        {"ticker": "TSLA", "price": 241.10,  "change": 14.80, "pct": 6.54},
    ]
    html = build_portfolio_digest_email(sample)
    sent = send_alert_email(user.email, "StockPulse · Test Alert Email", html)
    if not sent:
        raise HTTPException(500, "Failed to send — check RESEND_API_KEY in Railway env vars")
    return {"ok": True, "sent_to": user.email}


@router.put("/sync/state")
def save_state(body: StateBody, user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    if db is None:
        return {"ok": True}
    row = db.query(UserState).filter(UserState.user_id == user_id).first()
    if row:
        row.state = body.state
        row.updated_at = datetime.utcnow()
    else:
        db.add(UserState(user_id=user_id, state=body.state))
    db.commit()
    return {"ok": True}
