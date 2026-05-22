import logging
from typing import Protocol

from app.config import Settings
from app.rag.prompts import ANSWER_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class AnswerGenerator(Protocol):
    def generate(self, question: str, context: str) -> str:
        ...


class StubAnswerGenerator:
    def generate(self, question: str, context: str) -> str:
        return f"Нашел релевантные фрагменты:\n{context}"


class GigaChatAnswerGenerator:
    def __init__(self, settings: Settings) -> None:
        if not settings.gigachat_auth_key:
            raise RuntimeError(
                "GigaChat credentials are missing. Set GIGACHAT_CREDENTIALS in .env."
            )
        self.settings = settings
        self.llm = None

    def _get_llm(self):
        if self.llm is not None:
            return self.llm
        try:
            from langchain_gigachat import GigaChat
        except ImportError as exc:
            raise RuntimeError(
                "langchain-gigachat is not installed. Run: pip install langchain-gigachat"
            ) from exc

        logger.info("Initializing GigaChat LLM with model=%s", self.settings.gigachat_model)
        self.llm = GigaChat(
            credentials=self.settings.gigachat_auth_key,
            scope=self.settings.gigachat_scope,
            model=self.settings.gigachat_model,
            verify_ssl_certs=self.settings.gigachat_verify_ssl_certs,
            profanity_check=self.settings.gigachat_profanity_check,
        )
        return self.llm

    def generate(self, question: str, context: str) -> str:
        prompt = (
            f"{ANSWER_SYSTEM_PROMPT}\n\n"
            f"Контекст:\n{context}\n\n"
            f"Вопрос:\n{question}\n\n"
            "Ответ:"
        )
        response = self._get_llm().invoke(prompt)
        return getattr(response, "content", str(response))


def build_answer_generator(settings: Settings) -> AnswerGenerator:
    if settings.llm_provider.lower() == "gigachat":
        logger.info("Building GigaChat answer generator")
        return GigaChatAnswerGenerator(settings)
    logger.info("Building stub answer generator")
    return StubAnswerGenerator()
