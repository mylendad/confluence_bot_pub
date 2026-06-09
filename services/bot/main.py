import asyncio
import copy
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import BackgroundTasks, Body, FastAPI, HTTPException, status
from fastapi import Path as FastPath
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from services.bot.http_adapter import (
    AskRequest,
    AskResponse,
    ChatHistoryMessage,
    ExternalHealthResponse,
    MessageResponse,
    QuestionTemplate,
    SyncLastEventsResponse,
    SyncStatusResponse,
    TokensSaveRequest,
    TokensStatusResponse,
)
from services.bot.service import BotService
from shared.config.config import get_settings
from shared.factory import (
    build_chat_history_repository,
    build_confluence_client,
    build_llm_generator,
    build_metadata_repository,
    build_retriever,
    build_state_repository,
)
from shared.logging.logging_config import configure_logging, memory_handler
from shared.storage.chat_history_repository import ChatMessage

# --- Работа с .env (абсолютный путь) ---
BASE_DIR = Path(__file__).parent.parent.parent
ENV_PATH = BASE_DIR / ".env"

app = FastAPI(
    title="Confluence S2T RAG Bot",
    description="API для работы с RAG-ботом по документации витрин данных",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)
configure_logging()
logger = logging.getLogger(__name__)

# Global registry for active background processes
_active_processes: dict[str, asyncio.subprocess.Process] = {}

# --- Эндпоинты для управления токенами ---
@app.post(
    "/api/save-tokens",
    response_model=MessageResponse,
    status_code=status.HTTP_403_FORBIDDEN,
    summary="Сохранить токены (отключено)",
    tags=["Settings"],
    description="Сохранение токенов через API отключено в целях безопасности. Настройте .env файл.",
)
async def save_tokens(
    request: Annotated[TokensSaveRequest, Body(description="Набор токенов для сохранения")],
):
    raise HTTPException(status_code=403, detail="Изменение настроек через API отключено в целях безопасности. Пожалуйста, пропишите токены напрямую в .env файле.")


@app.post(
    "/api/clear-tokens",
    response_model=MessageResponse,
    status_code=status.HTTP_403_FORBIDDEN,
    summary="Удалить токены (отключено)",
    tags=["Settings"],
    description="Удаление токенов через API отключено в целях безопасности.",
)
async def clear_tokens():
    raise HTTPException(status_code=403, detail="Изменение настроек через API отключено в целях безопасности. Пожалуйста, очистите токены напрямую в .env файле.")



@app.get(
    "/api/tokens-status",
    response_model=TokensStatusResponse,
    summary="Статус токенов",
    tags=["Settings"],
)
async def tokens_status():
    settings = get_settings()
    c_ok = bool(settings.confluence_token)
    j_ok = bool(settings.jira_token)
    g_ok = bool(settings.gigachat_credentials)
    return TokensStatusResponse(
        configured=c_ok and j_ok and g_ok, confluence=c_ok, jira=j_ok, gigachat=g_ok
    )


# --- Фоновые команды ---
_is_update_running = False

def _run_update_rag_task():
    global _is_update_running
    try:
        from services.scenarios.update_rag_service import UpdateRagService
        service = UpdateRagService()
        service.run()
    except Exception as e:
        logger.exception(f"Ошибка фонового обновления RAG: {e}")
    finally:
        _is_update_running = False


@app.post(
    "/api/update-rag",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Обновить RAG",
    tags=["Commands"],
)
async def update_rag(background_tasks: BackgroundTasks):
    global _is_update_running
    if _is_update_running:
        return MessageResponse(message="Обновление уже запущено")
    
    _is_update_running = True
    background_tasks.add_task(_run_update_rag_task)
    return MessageResponse(message="Фоновое обновление запущено")


@app.post(
    "/api/interrupt-update",
    response_model=MessageResponse,
    summary="Прервать обновление RAG",
    tags=["Commands"],
)
async def interrupt_update():
    global _is_update_running
    if _is_update_running:
        raise HTTPException(
            status_code=501, 
            detail="В новой архитектуре принудительное прерывание синхронизации временно не поддерживается."
        )
    return MessageResponse(message="Процесс обновления не найден или уже завершен")


@app.post(
    "/api/shutdown", response_model=MessageResponse, summary="Выключить сервер", tags=["System"]
)
async def shutdown(background_tasks: BackgroundTasks):
    async def _s():
        await asyncio.sleep(0.5)
        sys.exit(0)

    background_tasks.add_task(_s)
    return MessageResponse(message="Сервер останавливается")


@app.post(
    "/api/clear-chat-history", response_model=MessageResponse, summary="Очистить чат", tags=["Chat"]
)
async def clear_chat_history(
    request: Annotated[dict[str, Any], Body(example={"session_id": "123"})],
):
    sid = request.get("session_id")
    if not sid:
        raise HTTPException(400, "session_id required")
    repo = build_chat_history_repository()
    with repo.db.connect() as conn:
        conn.execute("DELETE FROM chat_history WHERE session_id = ?", (sid,))
    return MessageResponse(message="История очищена")


@app.get("/api/logs/download", summary="Скачать логи", tags=["System"])
async def download_logs():
    return Response(
        content="\n".join(memory_handler.get_logs()),
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=logs.txt"},
    )


# --- Бизнес-логика ---
@app.get("/api/datamarts/list", response_model=list[str], summary="Список витрин", tags=["Data"])
async def list_datamarts():
    import re

    from shared.utils.text_utils import normalize_text

    meta_repo = build_metadata_repository()
    datamarts = meta_repo.list_datamarts()
    junk = r"\bтз\b|техническ[ои][еи] задани[ея]|чек лист|препятствия|функциональное решение|функцональное решение|страниц[аы] для 2лс|копия|изменения в релизах"
    filtered = []
    for dm in datamarts:
        name = dm.get("name", "")
        if not name:
            continue
        if "inner" in name.lower():
            filtered.append(name)
            continue
        if re.search(junk, normalize_text(name), re.IGNORECASE):
            continue
        if re.search(r"тз\s*-|тз\s*--", name.lower()):
            continue
        filtered.append(name)
    return sorted(set(filtered))


@app.post("/ask", response_model=AskResponse, summary="Задать вопрос", tags=["Chat"])
async def ask(request: Annotated[AskRequest, Body()]):
    settings = copy.deepcopy(get_settings())
    if request.confluence_token:
        settings.confluence_token = request.confluence_token
    if request.gigachat_token:
        settings.gigachat_credentials = request.gigachat_token
    try:
        service = BotService(build_retriever(settings))
        answer = service.ask(request.question)
        if request.session_id:
            repo = build_chat_history_repository(settings)
            repo.add(
                ChatMessage(
                    session_id=request.session_id,
                    user_message=request.question,
                    bot_response=answer.answer,
                    sources=[s.get("url") or s.get("file_name") or "" for s in answer.sources],
                    created_at=datetime.utcnow(),
                )
            )
        return AskResponse(answer=answer.answer, sources=answer.sources)
    except Exception as e:
        logger.exception("Ask error")
        raise HTTPException(500, detail=str(e)) from e


@app.get("/health", summary="Health check", tags=["System"])
async def health():
    return {"status": "ok"}


@app.get(
    "/api/health/external",
    response_model=ExternalHealthResponse,
    summary="Статус внешних систем",
    tags=["System"],
)
async def health_external():
    client_c, client_l = build_confluence_client(), build_llm_generator()
    from shared.factory import build_jira_client

    j = build_jira_client()
    return ExternalHealthResponse(
        confluence=client_c.check_health(), gigachat=client_l.check_health(), jira=j.check_health()
    )


@app.get("/api/logs", response_model=list[str], summary="Логи", tags=["System"])
async def get_logs():
    return memory_handler.get_logs()


@app.get(
    "/api/questions/templates",
    response_model=list[QuestionTemplate],
    summary="Шаблоны",
    tags=["Chat"],
)
async def get_question_templates():
    return [
        QuestionTemplate(
            id="owner", label="Владелец витрины", template="Кто владелец витрины {datamart}?"
        ),
        QuestionTemplate(
            id="attributes",
            label="Состав атрибутов",
            template="Какие атрибуты входят в витрину {datamart}?",
        ),
        QuestionTemplate(
            id="logic",
            label="Логика расчета",
            template="Какая логика расчета у атрибута {attribute} в витрине {datamart}?",
        ),
        QuestionTemplate(
            id="history",
            label="История изменений",
            template="Какие последние изменения были в витрине {datamart}?",
        ),
    ]


@app.get(
    "/api/sync/last-events",
    response_model=SyncLastEventsResponse,
    summary="События синхронизации",
    tags=["Sync"],
)
async def get_sync_last_events():
    s_repo, m_repo = build_state_repository(), build_metadata_repository()
    states, dms = s_repo.list_all(), m_repo.list_datamarts()
    lp = max([s.last_synced_at for s in states if s.last_synced_at]).isoformat() if states else None
    lru = max([d.get("updated_at") for d in dms if d.get("updated_at")]) if dms else None
    return SyncLastEventsResponse(last_parsing=lp, last_rag_update=lru, status="ok")


@app.get(
    "/api/sync/status",
    response_model=SyncStatusResponse,
    summary="Статус синхронизации",
    tags=["Sync"],
)
async def get_sync_status():
    repo = build_state_repository()
    states = repo.list_all()
    if not states:
        return SyncStatusResponse(last_sync=None, total_datamarts=0, status="no_data", resources=[])
    ls = (
        max([s.last_synced_at for s in states if s.last_synced_at]).isoformat()
        if any(s.last_synced_at for s in states)
        else None
    )
    res = [
        {
            "datamart": s.datamart_name,
            "file": s.file_name,
            "last_synced": s.last_synced_at.isoformat() if s.last_synced_at else None,
            "status": "synced" if s.content_hash else "pending",
        }
        for s in states
    ]
    return SyncStatusResponse(
        last_sync=ls,
        total_datamarts=len(set(s.datamart_name for s in states)),
        status="ok",
        resources=res,
    )


@app.get(
    "/api/chat/history/{session_id}",
    response_model=list[ChatHistoryMessage],
    summary="История чата",
    tags=["Chat"],
)
async def get_chat_history(session_id: Annotated[str, FastPath(description="ID сессии")]):
    repo = build_chat_history_repository()
    msgs = repo.list_by_session(session_id)
    return [
        ChatHistoryMessage(
            user=m.user_message,
            bot=m.bot_response,
            sources=m.sources,
            timestamp=m.created_at.isoformat(),
        )
        for m in msgs
    ]


static_path = BASE_DIR / "web"
app.mount("/ui", StaticFiles(directory=str(static_path), html=True), name="ui")


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/ui/")
