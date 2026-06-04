import os
import copy
import subprocess
import sys
import asyncio
import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from services.bot.http_adapter import AskRequest, AskResponse
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
from shared.logging.logging_config import memory_handler, configure_logging
from shared.storage.chat_history_repository import ChatMessage
from shared.storage.metadata_repository import MetadataRepository
from shared.storage.sqlite import SQLite

# --- Работа с .env (абсолютный путь) ---
BASE_DIR = Path(__file__).parent.parent.parent
ENV_PATH = BASE_DIR / ".env"

# Базовые константы, которые всегда должны быть в .env
DEFAULT_ENV_VARS = {
    "DATAMART_PAGE_PATTERN": "Витрина",
    "CONFLUENCE_BASE_URL": "https://confluence.delta.sbrf.ru",
    "CONFLUENCE_SPACE_KEY": "TEAM",
    "CONFLUENCE_AUTH_TYPE": "bearer",
    "CONFLUENCE_VERIFY_SSL": "false",
    "DATA_DIR": "./data",
    "CONFLUENCE_ROOT_PAGE_ID": "14561190342",
    "SQLITE_DB_PATH": "./data/app.db",
    "VECTOR_STORE_DIR": "./data/vector_store",
    "RAG_UPDATE_CRON": "0 2 * * *",
    "CHANGE_HISTORY_DAYS": "365",
    "EMBEDDING_PROVIDER": "local",
    "EMBEDDING_MODEL": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "LLM_PROVIDER": "gigachat",
    "GIGACHAT_SCOPE": "GIGACHAT_API_PERS",
    "GIGACHAT_MODEL": "GigaChat",
    "JIRA_BASE_URL": "https://jira.delta.sbrf.ru",
    "JIRA_VERIFY_SSL": "false",
}


def _update_env_file(updates: dict):
    """Обновляет или добавляет переменные в .env, сохраняя остальные."""
    lines = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()

    updated_keys = set()
    new_lines = []

    # Обновляем существующие строки
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                updated_keys.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    # Добавляем новые переменные, которых не было
    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(new_lines), encoding="utf-8")

    # Сбрасываем кэш настроек после изменения .env
    get_settings.cache_clear()


class TokensSaveRequest(BaseModel):
    confluence_token: str | None = None
    jira_token: str | None = None
    gigachat_token: str | None = None


class TokensStatusResponse(BaseModel):
    configured: bool
    confluence: bool
    jira: bool
    gigachat: bool


app = FastAPI(title="Confluence S2T RAG Bot")
configure_logging()
logger = logging.getLogger(__name__)


# --- Эндпоинты для управления токенами ---
@app.post("/api/save-tokens")
async def save_tokens(request: TokensSaveRequest):
    """Сохраняет переданные токены в .env."""
    updates = {}
    if request.confluence_token is not None:
        updates["CONFLUENCE_TOKEN"] = request.confluence_token
    if request.jira_token is not None:
        updates["JIRA_TOKEN"] = request.jira_token
        updates["JIRA_API_TOKEN"] = request.jira_token
    if request.gigachat_token is not None:
        updates["GIGACHAT_CREDENTIALS"] = request.gigachat_token
        updates["GIGACHAT_API_PERS"] = request.gigachat_token
    if updates:
        _update_env_file(updates)
    return {"message": "Токены сохранены"}


@app.post("/api/clear-tokens")
async def clear_tokens():
    """Очищает токены в .env (устанавливает пустые значения)."""
    updates = {
        "CONFLUENCE_TOKEN": "",
        "JIRA_TOKEN": "",
        "JIRA_API_TOKEN": "",
        "GIGACHAT_CREDENTIALS": "",
        "GIGACHAT_API_PERS": "",
    }
    _update_env_file(updates)
    return {"message": "Токены удалены"}


@app.get("/api/tokens-status")
async def tokens_status():
    """Возвращает, какие токены заданы в .env."""
    settings = get_settings()
    confluence_ok = bool(settings.confluence_token)
    jira_ok = bool(settings.jira_token)
    gigachat_ok = bool(settings.gigachat_credentials)
    configured = confluence_ok and jira_ok and gigachat_ok
    return TokensStatusResponse(
        configured=configured, confluence=confluence_ok, jira=jira_ok, gigachat=gigachat_ok
    )


# --- Фоновые команды с реальным временем логов ---
async def _run_cli_command_streaming(args: list[str], command_name: str):
    """Запускает CLI команду и построчно логирует вывод в реальном времени."""
    try:
        logger.info("Запуск команды %s: python -m services.bot.cli %s", command_name, " ".join(args))
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "services.bot.cli",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )

        async def read_stream(stream, log_func):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    log_func("[CLI] %s", text)
                    for handler in logging.getLogger().handlers:
                        handler.flush()

        await asyncio.gather(
            read_stream(process.stdout, logger.info), read_stream(process.stderr, logger.error)
        )
        return_code = await process.wait()
        if return_code == 0:
            logger.info("✅ Команда %s завершена успешно", command_name)
        else:
            logger.error("❌ Команда %s завершена с кодом %d", command_name, return_code)
    except Exception as e:
        logger.exception("Ошибка при выполнении команды %s: %s", command_name, e)


@app.post("/api/update-rag")
async def update_rag(background_tasks: BackgroundTasks):
    """Запускает инкрементальное обновление RAG в фоне с потоковым логированием."""
    background_tasks.add_task(_run_cli_command_streaming, ["update-rag"], "update-rag")
    return {"message": "Команда update-rag запущена в фоне. Смотрите логи."}


@app.post("/api/shutdown")
async def shutdown(background_tasks: BackgroundTasks):
    """Останавливает сервер."""

    async def _shutdown():
        await asyncio.sleep(0.5)
        logger.info("Shutting down server...")
        sys.exit(0)

    background_tasks.add_task(_shutdown)
    return {"message": "Сервер останавливается..."}


@app.post("/api/clear-chat-history")
async def clear_chat_history(request: dict):
    session_id = request.get("session_id")
    if not session_id:
        raise HTTPException(400, "session_id required")
    repo = build_chat_history_repository()
    with repo.db.connect() as conn:
        conn.execute("delete from chat_history where session_id = ?", (session_id,))
    return {"message": "История очищена"}


@app.get("/api/logs/download")
async def download_logs():
    """Скачать текущие логи в файл."""
    logs = memory_handler.get_logs()
    content = "\n".join(logs)
    return Response(
        content=content,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=logs.txt"},
    )


# --- Список витрин для инлайн-кнопок ---
def _clean_datamart_list():
    """Возвращает отфильтрованный список витрин (как в RAGRetriever._datamart_list)."""
    import re
    from shared.utils.text_utils import normalize_text

    meta_repo = build_metadata_repository()
    datamarts = meta_repo.list_datamarts()
    junk_patterns = [
        r"\bтз\b",
        r"техническ[ои][еи] задани[ея]",
        r"чек лист",
        r"препятствия",
        r"функциональное решение",
        r"функцональное решение",
        r"страниц[аы] для 2лс",
        r"копия",
        r"изменения в релизах",
    ]
    combined_junk = "|".join(junk_patterns)
    filtered = []
    for dm in datamarts:
        name = dm.get("name", "")
        if not name:
            continue
        if "inner" in name.lower():
            filtered.append(name)
            continue
        norm_name = normalize_text(name)
        if re.search(combined_junk, norm_name):
            continue
        if re.search(r"тз\s*-|тз\s*--", name.lower()):
            continue
        filtered.append(name)
    return sorted(set(filtered))


@app.get("/api/datamarts/list")
async def list_datamarts():
    return _clean_datamart_list()


# --- Остальные эндпоинты ---
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
async def health_external():
    conf_client = build_confluence_client()
    llm_gen = build_llm_generator()
    from shared.factory import build_jira_client

    jira_client = build_jira_client()
    conf_status = conf_client.check_health()
    jira_status = jira_client.check_health()
    llm_status = llm_gen.check_health()
    logger.info(
        "Health check: Confluence=%s, Jira=%s, GigaChat=%s (details: %s)",
        conf_status.get("status"),
        jira_status.get("status"),
        llm_status.get("status"),
        llm_status,
    )
    return {"confluence": conf_status, "gigachat": llm_status, "jira": jira_status}


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
    last_parsing = None
    if states:
        valid = [s.last_synced_at for s in states if s.last_synced_at]
        if valid:
            last_parsing = max(valid)

    meta_repo = build_metadata_repository()
    datamarts = meta_repo.list_datamarts()
    last_meta_update = None
    if datamarts:
        updates = [d.get("updated_at") for d in datamarts if d.get("updated_at")]
        if updates:
            last_meta_update = max(updates)
    return {
        "last_parsing": last_parsing.isoformat() if last_parsing else None,
        "last_rag_update": last_meta_update,
        "status": "ok",
    }


@app.get("/api/sync/status")
def get_sync_status() -> dict:
    repo = build_state_repository()
    states = repo.list_all()
    if not states:
        return {"last_sync": None, "total_datamarts": 0, "status": "no_data"}
    last_sync = None
    if any(s.last_synced_at for s in states):
        last_sync = max(s.last_synced_at for s in states if s.last_synced_at)
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


# --- Монтирование статики и редирект ---
static_path = BASE_DIR / "web"

app.mount("/ui", StaticFiles(directory=str(static_path), html=True), name="ui")


@app.get("/")
async def root():
    return RedirectResponse(url="/ui/")
