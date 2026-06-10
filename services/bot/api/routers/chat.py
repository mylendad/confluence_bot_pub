import copy
import logging
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException
from fastapi import Path as FastPath

from services.bot.http_adapter import (
    AskRequest,
    AskResponse,
    ChatHistoryMessage,
    MessageResponse,
    QuestionTemplate,
)
from services.bot.service import BotService
from shared.config.config import get_settings
from shared.factory import build_chat_history_repository, build_retriever
from shared.storage.chat_history_repository import ChatMessage

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Chat"])

@router.post("/ask", response_model=AskResponse, summary="Задать вопрос")
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

@router.get(
    "/api/questions/templates",
    response_model=list[QuestionTemplate],
    summary="Шаблоны",
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

@router.get(
    "/api/chat/history/{session_id}",
    response_model=list[ChatHistoryMessage],
    summary="История чата",
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

@router.post(
    "/api/clear-chat-history", response_model=MessageResponse, summary="Очистить чат"
)
async def clear_chat_history(
    request: Annotated[dict[str, Any], Body(example={"session_id": "123"})],
):
    sid = request.get("session_id")
    if not sid:
        raise HTTPException(400, "session_id required")
    from services.scenarios.chat_history_service import ChatHistoryService
    ChatHistoryService().clear_history(sid)
    return MessageResponse(message="История очищена")
