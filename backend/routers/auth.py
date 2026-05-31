import os
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from passlib.context import CryptContext
from jose import jwt

from database import get_db, User

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
    if db.query(User).filter(User.email == body.email.lower()).first():
        raise HTTPException(400, "Email already registered")
    user = User(email=body.email.lower(), hashed_password=pwd.hash(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"access_token": make_token(user.id), "email": user.email}


@router.post("/auth/login")
def login(body: AuthBody, db: Session = Depends(get_db)):
    if db is None:
        raise HTTPException(503, "Database not configured")
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user or not pwd.verify(body.password, user.hashed_password):
        raise HTTPException(401, "Invalid email or password")
    return {"access_token": make_token(user.id), "email": user.email}
