import asyncio
import sys

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import Response

from services.bot.http_adapter import ExternalHealthResponse, MessageResponse
from shared.factory import build_confluence_client, build_jira_client, build_llm_generator
from shared.logging.logging_config import memory_handler

router = APIRouter(tags=["System"])

@router.post("/api/shutdown", response_model=MessageResponse, summary="Выключить сервер")
async def shutdown(background_tasks: BackgroundTasks):
    async def _s():
        await asyncio.sleep(0.5)
        sys.exit(0)

    background_tasks.add_task(_s)
    return MessageResponse(message="Сервер останавливается")

@router.get("/api/logs/download", summary="Скачать логи")
async def download_logs():
    return Response(
        content="\n".join(memory_handler.get_logs()),
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=logs.txt"},
    )

@router.get("/health", summary="Health check")
async def health():
    return {"status": "ok"}

@router.get(
    "/api/health/external",
    response_model=ExternalHealthResponse,
    summary="Статус внешних систем",
)
async def health_external():
    client_c = build_confluence_client()
    client_l = build_llm_generator()
    j = build_jira_client()
    return ExternalHealthResponse(
        confluence=client_c.check_health(), 
        gigachat=client_l.check_health(), 
        jira=j.check_health()
    )

@router.get("/api/logs", response_model=list[str], summary="Логи")
async def get_logs():
    return memory_handler.get_logs()
