import os
import logging
from sqlalchemy import create_engine, Column, Integer, String, Float, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserState(Base):
    __tablename__ = "user_states"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    state = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SentAlert(Base):
    __tablename__ = "sent_alerts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    ticker = Column(String, nullable=False)
    alert_type = Column(String, nullable=False)  # "target_hit" | "big_move"
    price_at_send = Column(Float)
    sent_at = Column(DateTime, default=datetime.utcnow)


engine = None
SessionLocal = None


def init_db() -> bool:
    global engine, SessionLocal
    if not DATABASE_URL:
        logger.warning("DATABASE_URL not set — auth/sync disabled")
        return False
    try:
        kwargs = {"pool_pre_ping": True}
        # Railway PostgreSQL requires SSL
        if "railway" in DATABASE_URL or "rlwy" in DATABASE_URL or "railwayapp" in DATABASE_URL:
            kwargs["connect_args"] = {"sslmode": "require"}
        engine = create_engine(DATABASE_URL, **kwargs)
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        logger.info("Database initialised")
        return True
    except Exception as e:
        logger.error("DB init failed: %s", e)
        return False


def get_db():
    if not SessionLocal:
        yield None
        return
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
