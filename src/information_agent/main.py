from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from contextlib import asynccontextmanager
from threading import Event, Thread
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from information_agent.api import router
from information_agent.config import settings
from information_agent.db import SessionLocal
from information_agent.sync_worker import run_loop

@asynccontextmanager
async def lifespan(_app: FastAPI):
    stop = Event()
    thread = None
    if settings.sync_in_web:
        thread = Thread(target=run_loop, args=(stop,), daemon=True)
        thread.start()
    yield
    stop.set()
    if thread is not None:
        thread.join(timeout=2)


app = FastAPI(title="个人资讯 Agent", version="0.1.0", lifespan=lifespan)
if settings.app_env != "local":
    for key, value, minimum in (
        ("APP_SECRET", settings.app_secret, 32),
        ("ADMIN_TOKEN", settings.admin_token, 32),
        ("REGISTRATION_CODE", settings.registration_code, 10),
    ):
        if len(value) < minimum or value.startswith(("replace-", "local-development-")):
            raise RuntimeError(f"{key} must be a private value of at least {minimum} characters")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type", "X-Admin-Token"],
)
app.include_router(router)


@app.get("/health", tags=["运行状态"])
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}


@app.get("/ready", tags=["运行状态"])
def ready() -> dict[str, str]:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="数据库暂不可用") from None
    return {"status": "ready"}


web_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
if web_dist.is_dir():
    app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
