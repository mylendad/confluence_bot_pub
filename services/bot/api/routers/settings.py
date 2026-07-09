from typing import Annotated
from pathlib import Path
from fastapi import APIRouter, Body, status

from services.bot.http_adapter import (
    MessageResponse,
    TokensSaveRequest,
    TokensStatusResponse,
)
from shared.config.config import get_settings

router = APIRouter(tags=["Settings"])

BASE_DIR = Path(__file__).parent.parent.parent.parent.parent
ENV_PATH = BASE_DIR / ".env"

def _update_env_file(updates: dict[str, str]):
    """Обновляет или добавляет переменные в .env, сохраняя остальные."""
    lines = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()

    updated_keys = set()
    new_lines = []

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

    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(new_lines), encoding="utf-8")
    get_settings.cache_clear()

@router.post(
    "/api/save-tokens",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Сохранить токены",
)
async def save_tokens(
    request: Annotated[TokensSaveRequest, Body(description="Набор токенов для сохранения")],
):
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

    return MessageResponse(message="Токены сохранены")

@router.post(
    "/api/clear-tokens",
    response_model=MessageResponse,
    summary="Удалить токены",
)
async def clear_tokens():
    updates = {
        "CONFLUENCE_TOKEN": "",
        "JIRA_TOKEN": "",
        "JIRA_API_TOKEN": "",
        "GIGACHAT_CREDENTIALS": "",
        "GIGACHAT_API_PERS": "",
    }
    _update_env_file(updates)
    return MessageResponse(message="Токены удалены")

@router.get(
    "/api/tokens-status",
    response_model=TokensStatusResponse,
    summary="Статус токенов",
)
async def tokens_status():
    settings = get_settings()
    c_ok = bool(settings.confluence_token)
    j_ok = bool(settings.jira_token)
    g_ok = bool(settings.gigachat_credentials)
    return TokensStatusResponse(
        configured=c_ok and j_ok and g_ok, 
        confluence=c_ok, 
        jira=j_ok, 
        gigachat=g_ok
    )
