import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from services.bot.http_adapter import MessageResponse, SyncLastEventsResponse, SyncStatusResponse
from services.scenarios.sync_status_service import SyncStatusService
from shared.logging.logging_config import memory_handler

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Sync"])

_is_update_running = False

def _run_update_rag_task():
    global _is_update_running
    command_name = "update-rag"
    try:
        from services.scenarios.update_rag_service import UpdateRagService
        service = UpdateRagService()
        service.run()
        logger.info(f"✅ Команда {command_name} завершена")
    except Exception as e:
        logger.error(f"❌ Команда {command_name} завершена с кодом 1")
        logger.exception(f"Ошибка фонового обновления RAG: {e}")
    finally:
        _is_update_running = False

@router.post(
    "/api/update-rag",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Обновить RAG",
)
async def update_rag(background_tasks: BackgroundTasks):
    global _is_update_running
    if _is_update_running:
        return MessageResponse(message="Обновление уже запущено")
    
    # Очищаем логи перед запуском нового обновления, чтобы UI не ловил старые сообщения
    memory_handler.clear()
    
    _is_update_running = True
    background_tasks.add_task(_run_update_rag_task)
    return MessageResponse(message="Фоновое обновление запущено")

@router.post(
    "/api/interrupt-update",
    response_model=MessageResponse,
    summary="Прервать обновление RAG",
)
async def interrupt_update():
    global _is_update_running
    if _is_update_running:
        raise HTTPException(
            status_code=501, 
            detail="В новой архитектуре принудительное прерывание синхронизации временно не поддерживается."
        )
    return MessageResponse(message="Процесс обновления не найден или уже завершен")

@router.get(
    "/api/sync/last-events",
    response_model=SyncLastEventsResponse,
    summary="События синхронизации",
)
async def get_sync_last_events():
    return SyncStatusService().get_last_events()

@router.get(
    "/api/sync/status",
    response_model=SyncStatusResponse,
    summary="Статус синхронизации",
)
async def get_sync_status():
    return SyncStatusService().get_status()
