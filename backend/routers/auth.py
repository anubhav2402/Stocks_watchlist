import os
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from passlib.context import CryptContext
from jose import jwt

from database import get_db, User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET = os.getenv("JWT_SECRET", "change-this-secret-in-production")
ALGO = "HS256"
TOKEN_DAYS = 30


def make_token(user_id: int) -> str:
    return jwt.encode(
        {"sub": str(user_id), "exp": datetime.utcnow() + timedelta(days=TOKEN_DAYS)},
        SECRET, algorithm=ALGO,
    )


class AuthBody(BaseModel):
    email: str
    password: str


@router.post("/auth/register")
def register(body: AuthBody, db: Session = Depends(get_db)):
    if db is None:
        raise HTTPException(503, "Database not configured")
    try:
        if db.query(User).filter(User.email == body.email.lower()).first():
            raise HTTPException(400, "Email already registered")
        pw = body.password.encode("utf-8")[:72].decode("utf-8", errors="ignore")
        user = User(email=body.email.lower(), hashed_password=pwd.hash(pw))
        db.add(user)
        db.commit()
        db.refresh(user)
        return {"access_token": make_token(user.id), "email": user.email}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Register error: %s", e, exc_info=True)
        raise HTTPException(500, f"Registration failed: {e}")


@router.post("/auth/login")
def login(body: AuthBody, db: Session = Depends(get_db)):
    if db is None:
        raise HTTPException(503, "Database not configured")
    try:
        user = db.query(User).filter(User.email == body.email.lower()).first()
        pw = body.password.encode("utf-8")[:72].decode("utf-8", errors="ignore")
        if not user or not pwd.verify(pw, user.hashed_password):
            raise HTTPException(401, "Invalid email or password")
        return {"access_token": make_token(user.id), "email": user.email}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Login error: %s", e, exc_info=True)
        raise HTTPException(500, f"Login failed: {e}")
