from pydantic import BaseModel


class AskRequest(BaseModel):
    question: str
    session_id: str | None = None
    confluence_token: str | None = None
    gigachat_token: str | None = None


class AskResponse(BaseModel):
    answer: str
    sources: list[dict]
