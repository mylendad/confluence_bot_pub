import copy
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.bot.http_adapter import AskRequest, AskResponse
from app.bot.service import BotService
from app.config import get_settings
from app.factory import (
    build_chat_history_repository,
    build_confluence_client,
    build_llm_generator,
    build_retriever,
    build_state_repository,
)
from app.logging_config import memory_handler
from app.storage.chat_history_repository import ChatMessage

app = FastAPI(title="Confluence S2T RAG Bot")


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    # Используем настройки из .env как базу, но позволяем переопределить токены из UI
    settings = copy.deepcopy(get_settings())
    if request.confluence_token:
        settings.confluence_token = request.confluence_token
        settings.confluence_api_token = request.confluence_token
    if request.gigachat_token:
        settings.gigachat_credentials = request.gigachat_token
        settings.gigachat_api_key = request.gigachat_token

    try:
        service = BotService(build_retriever(settings))
        answer = service.ask(request.question)

        if request.session_id:
            history_repo = build_chat_history_repository(settings)
            history_repo.add(
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
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health/external")
def health_external() -> dict:
    conf_client = build_confluence_client()
    llm_gen = build_llm_generator()
    from app.factory import build_jira_client
    jira_client = build_jira_client()

    return {
        "confluence": conf_client.check_health(),
        "gigachat": llm_gen.check_health(),
        "jira": jira_client.check_health()
    }


@app.get("/api/logs")
def get_logs() -> list[str]:
    return memory_handler.get_logs()


@app.get("/api/questions/templates")
def get_question_templates() -> list[dict]:
    return [
        {
            "id": "owner",
            "label": "Владелец витрины",
            "template": "Кто владелец витрины {datamart}?",
        },
        {
            "id": "attributes",
            "label": "Состав атрибутов",
            "template": "Какие атрибуты входят в витрину {datamart}?",
        },
        {
            "id": "logic",
            "label": "Логика расчета",
            "template": "Какая логика расчета у атрибута {attribute} в витрине {datamart}?",
        },
        {
            "id": "history",
            "label": "История изменений",
            "template": "Какие последние изменения были в витрине {datamart}?",
        },
    ]


@app.get("/api/sync/last-events")
def get_sync_last_events() -> dict:
    state_repo = build_state_repository()
    states = state_repo.list_all()
    
    # Последний парсинг (синхронизация файлов)
    last_parsing = None
    if states:
        last_parsing = max(s.last_synced_at for s in states if s.last_synced_at) if any(s.last_synced_at for s in states) else None

    # Последнее обновление метаданных (витрин)
    meta_repo = build_metadata_repository()
    datamarts = meta_repo.list_datamarts()
    last_meta_update = None
    if datamarts:
        # В таблице datamarts поле updated_at хранится как строка ISO
        updates = [d.get("updated_at") for d in datamarts if d.get("updated_at")]
        if updates:
            last_meta_update = max(updates)

    return {
        "last_parsing": last_parsing.isoformat() if last_parsing else None,
        "last_rag_update": last_meta_update,  # Это уже строка ISO
        "status": "ok"
    }


@app.get("/api/sync/status")
def get_sync_status() -> dict:
    repo = build_state_repository()
    states = repo.list_all()
    if not states:
        return {"last_sync": None, "total_datamarts": 0, "status": "no_data"}

    last_sync = (
        max(s.last_synced_at for s in states if s.last_synced_at)
        if any(s.last_synced_at for s in states)
        else None
    )

    return {
        "last_sync": last_sync.isoformat() if last_sync else None,
        "total_datamarts": len(set(s.datamart_name for s in states)),
        "resources": [
            {
                "datamart": s.datamart_name,
                "file": s.file_name,
                "last_synced": s.last_synced_at.isoformat() if s.last_synced_at else None,
                "status": "synced" if s.content_hash else "pending",
            }
            for s in states
        ],
    }


@app.get("/api/chat/history/{session_id}")
def get_chat_history(session_id: str) -> list[dict]:
    repo = build_chat_history_repository()
    messages = repo.list_by_session(session_id)
    return [
        {
            "user": m.user_message,
            "bot": m.bot_response,
            "sources": m.sources,
            "timestamp": m.created_at.isoformat(),
        }
        for m in messages
    ]


@app.get("/")
async def root():
    return RedirectResponse(url="/ui/")


# Монтируем статику
static_path = Path(__file__).parent / "static"
if not static_path.exists():
    static_path.mkdir(parents=True, exist_ok=True)

app.mount("/ui", StaticFiles(directory=str(static_path), html=True), name="ui")
