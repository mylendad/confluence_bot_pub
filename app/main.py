from fastapi import FastAPI

from app.bot.http_adapter import AskRequest, AskResponse
from app.bot.service import BotService
from app.factory import build_retriever

app = FastAPI(title="Confluence S2T RAG Bot")


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    service = BotService(build_retriever())
    answer = service.ask(request.question)
    return AskResponse(answer=answer.answer, sources=answer.sources)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
