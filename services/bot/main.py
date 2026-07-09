import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from services.bot.api.routers import (
    chat_router,
    data_router,
    settings_router,
    sync_router,
    system_router,
)
from shared.logging.logging_config import configure_logging

BASE_DIR = Path(__file__).parent.parent.parent

app = FastAPI(
    title="Confluence S2T RAG Bot",
    description="API для работы с RAG-ботом по документации витрин данных",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)
configure_logging()
logger = logging.getLogger(__name__)

app.include_router(settings_router)
app.include_router(chat_router)
app.include_router(sync_router)
app.include_router(system_router)
app.include_router(data_router)

static_path = BASE_DIR / "web"
app.mount("/ui", StaticFiles(directory=str(static_path), html=True), name="ui")

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/ui/")
