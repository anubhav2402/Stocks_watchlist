import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel
from jose import jwt, JWTError

from database import get_db, UserState

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
