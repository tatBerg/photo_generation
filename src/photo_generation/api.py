from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .db import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title=get_settings().bot_name, version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": "mock" if get_settings().mock_mode else "live"}


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": get_settings().bot_name, "status": "running"}
