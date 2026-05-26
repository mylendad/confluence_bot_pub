import logging
import time
from typing import Protocol

from app.config import Settings
from app.rag.prompts import ANSWER_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class AnswerGenerator(Protocol):
    def generate(self, question: str, context: str) -> str:
        ...

    def check_health(self) -> dict:
        ...


class StubAnswerGenerator:
    def generate(self, question: str, context: str) -> str:
        return f"Нашел релевантные фрагменты:\n{context}"

    def check_health(self) -> dict:
        return {"status": "ok", "provider": "stub"}


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

        max_retries = 3
        retry_delay = 1.0
        last_exc = None

        for attempt in range(max_retries):
            try:
                response = self._get_llm().invoke(prompt)
                return getattr(response, "content", str(response))
            except Exception as exc:
                last_exc = exc
                if "104" in str(exc) or "reset" in str(exc).lower():
                    logger.warning(
                        "GigaChat connection reset (attempt %d/%d), retrying in %.1fs...",
                        attempt + 1,
                        max_retries,
                        retry_delay,
                    )
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                raise exc

        raise last_exc

    def check_health(self) -> dict:
        start_time = time.time()
        try:
            # Simple ping to GigaChat
            self._get_llm().invoke("ping")
            latency = (time.time() - start_time) * 1000
            return {
                "status": "ok",
                "provider": "gigachat",
                "latency_ms": round(latency, 2),
                "model": self.settings.gigachat_model,
            }
        except Exception as exc:
            return {"status": "error", "provider": "gigachat", "message": str(exc)}


def build_answer_generator(settings: Settings) -> AnswerGenerator:
    if settings.llm_provider.lower() == "gigachat":
        logger.info("Building GigaChat answer generator")
        return GigaChatAnswerGenerator(settings)
    logger.info("Building stub answer generator")
    return StubAnswerGenerator()
