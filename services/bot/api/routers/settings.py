from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, status

from services.bot.http_adapter import MessageResponse, TokensSaveRequest, TokensStatusResponse
from shared.config.config import get_settings

router = APIRouter(tags=["Settings"])

@router.post(
    "/api/save-tokens",
    response_model=MessageResponse,
    status_code=status.HTTP_403_FORBIDDEN,
    summary="Сохранить токены (отключено)",
    description="Сохранение токенов через API отключено в целях безопасности. Настройте .env файл.",
)
async def save_tokens(
    request: Annotated[TokensSaveRequest, Body(description="Набор токенов для сохранения")],
):
    raise HTTPException(status_code=403, detail="Изменение настроек через API отключено в целях безопасности. Пожалуйста, пропишите токены напрямую в .env файле.")


@router.post(
    "/api/clear-tokens",
    response_model=MessageResponse,
    status_code=status.HTTP_403_FORBIDDEN,
    summary="Удалить токены (отключено)",
    description="Удаление токенов через API отключено в целях безопасности.",
)
async def clear_tokens():
    raise HTTPException(status_code=403, detail="Изменение настроек через API отключено в целях безопасности. Пожалуйста, очистите токены напрямую в .env файле.")


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
        configured=c_ok and j_ok and g_ok, confluence=c_ok, jira=j_ok, gigachat=g_ok
    )
