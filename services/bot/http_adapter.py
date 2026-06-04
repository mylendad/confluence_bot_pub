from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any


class AskRequest(BaseModel):
    """
    Запрос на получение ответа от бота.
    """
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question": "Кто владелец витрины клиентских операций?",
                "session_id": "session_123"
            }
        }
    )
    question: str = Field(..., description="Вопрос пользователя")
    session_id: Optional[str] = Field(None, description="Идентификатор сессии для сохранения истории")
    confluence_token: Optional[str] = Field(None, description="Опциональный токен Confluence (перекрывает системный)")
    gigachat_token: Optional[str] = Field(None, description="Опциональный токен GigaChat (перекрывает системный)")


class AskResponse(BaseModel):
    """
    Ответ бота с текстом и источниками.
    """
    answer: str = Field(..., description="Текстовый ответ бота")
    sources: List[Dict[str, Any]] = Field(default_factory=list, description="Список источников информации")


class TokensSaveRequest(BaseModel):
    """
    Запрос на сохранение токенов доступа.
    """
    confluence_token: Optional[str] = Field(None, description="Токен для Confluence")
    jira_token: Optional[str] = Field(None, description="Токен для Jira")
    gigachat_token: Optional[str] = Field(None, description="Токен для GigaChat")


class TokensStatusResponse(BaseModel):
    """
    Статус настройки токенов в системе.
    """
    configured: bool = Field(..., description="Все ли токены настроены")
    confluence: bool = Field(..., description="Настроен ли токен Confluence")
    jira: bool = Field(..., description="Настроен ли токен Jira")
    gigachat: bool = Field(..., description="Настроен ли токен GigaChat")


class HealthStatus(BaseModel):
    """
    Статус работоспособности сервиса.
    """
    status: str = Field(..., description="Статус сервиса (ok/error)")
    details: Optional[Dict[str, Any]] = Field(None, description="Дополнительные детали статуса")


class ExternalHealthResponse(BaseModel):
    """
    Статус подключения к внешним системам.
    """
    confluence: Dict[str, Any] = Field(..., description="Статус подключения к Confluence")
    gigachat: Dict[str, Any] = Field(..., description="Статус подключения к GigaChat")
    jira: Dict[str, Any] = Field(..., description="Статус подключения к Jira")


class SyncStatusResource(BaseModel):
    """
    Статус синхронизации конкретного ресурса (витрины).
    """
    datamart: str = Field(..., description="Название витрины")
    file: str = Field(..., description="Имя файла S2T")
    last_synced: Optional[str] = Field(None, description="Время последней синхронизации (ISO)")
    status: str = Field(..., description="Текущий статус ресурса")


class SyncStatusResponse(BaseModel):
    """
    Общий статус синхронизации всех витрин.
    """
    last_sync: Optional[str] = Field(None, description="Время самой свежей синхронизации")
    total_datamarts: int = Field(..., description="Общее количество витрин в базе")
    status: str = Field(..., description="Общий статус синхронизации")
    resources: List[SyncStatusResource] = Field(default_factory=list, description="Детальный список ресурсов")


class SyncLastEventsResponse(BaseModel):
    """
    Информация о последних событиях синхронизации.
    """
    last_parsing: Optional[str] = Field(None, description="Время последнего парсинга файлов")
    last_rag_update: Optional[str] = Field(None, description="Время последнего обновления RAG-индекса")
    status: str = Field(..., description="Статус")


class ChatHistoryMessage(BaseModel):
    """
    Запись в истории чата.
    """
    user: str = Field(..., description="Сообщение пользователя")
    bot: str = Field(..., description="Ответ бота")
    sources: List[str] = Field(default_factory=list, description="Список ссылок на источники")
    timestamp: str = Field(..., description="Время сообщения (ISO)")


class QuestionTemplate(BaseModel):
    """
    Шаблон вопроса для UI.
    """
    id: str = Field(..., description="Уникальный ID шаблона")
    label: str = Field(..., description="Человекочитаемое название")
    template: str = Field(..., description="Текст шаблона с плейсхолдерами")


class MessageResponse(BaseModel):
    """
    Простой информационный ответ от сервера.
    """
    message: str = Field(..., description="Информационное сообщение от сервера")
