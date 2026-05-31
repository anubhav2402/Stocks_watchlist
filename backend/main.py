from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import ALLOWED_ORIGINS, write_cookies_from_env
from routers import health, quotes, news, accounts, discovery
from routers import research_router
from routers import auth as auth_router
from routers import sync as sync_router
from database import init_db
import scheduler as sched


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ────────────────────────────────────────────────────────────────
    init_db()
    if write_cookies_from_env():
        import logging
        logging.getLogger(__name__).info("Twitter cookies restored from TWITTER_COOKIES_B64 env var")
    await sched.startup()
    yield
    # ── Shutdown ───────────────────────────────────────────────────────────────
    await sched.shutdown()


app = FastAPI(
    title="StockPulse API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(quotes.router, prefix="/api")
app.include_router(news.router, prefix="/api")
app.include_router(accounts.router, prefix="/api")
app.include_router(discovery.router, prefix="/api")
app.include_router(research_router.router, prefix="/api")
app.include_router(auth_router.router, prefix="/api")
app.include_router(sync_router.router, prefix="/api")


@app.get("/")
def root():
    return {"status": "ok", "service": "StockPulse API", "version": "2.0.0"}
