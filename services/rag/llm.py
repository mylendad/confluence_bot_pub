import logging
import time
from typing import Protocol

from services.rag.prompts import ANSWER_SYSTEM_PROMPT
from shared.config.config import Settings

logger = logging.getLogger(__name__)


class AnswerGenerator(Protocol):
    """Интерфейс для генератора ответов на основе LLM."""

    def generate(self, question: str, context: str) -> str:
        """
        Генерирует текстовый ответ на основе вопроса и контекста.
        :param question: Текст вопроса.
        :param context: Текстовый контекст для генерации ответа.
        """
        ...

    def check_health(self) -> dict:
        """Проверяет работоспособность сервиса генерации."""
        ...


class StubAnswerGenerator:
    """Заглушка генератора ответов, возвращающая только контекст."""

    def generate(self, question: str, context: str) -> str:
        """Возвращает найденный контекст в качестве ответа."""
        return f"Нашел релевантные фрагменты:\n{context}"

    def check_health(self) -> dict:
        """Всегда возвращает статус ok."""
        return {"status": "ok", "provider": "stub"}


class GigaChatAnswerGenerator:
    """Генератор ответов на базе GigaChat LLM."""

    def __init__(self, settings: Settings) -> None:
        """
        Инициализирует GigaChatAnswerGenerator.
        :param settings: Объект настроек приложения.
        """
        if not settings.gigachat_auth_key:
            raise RuntimeError(
                "GigaChat credentials are missing. Set GIGACHAT_CREDENTIALS in .env."
            )
        self.settings = settings
        self.llm = None

    def _get_llm(self):
        """Ленивая инициализация объекта LangChain GigaChat."""
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
            timeout=30.0,  # Add explicit timeout
        )
        return self.llm

    def generate(self, question: str, context: str) -> str:
        """
        Вызывает GigaChat для генерации ответа на вопрос.
        :param question: Текст вопроса.
        :param context: Найденный контекст.
        """
        prompt = f"{ANSWER_SYSTEM_PROMPT}\n\nКонтекст:\n{context}\n\nВопрос:\n{question}\n\nОтвет:"

        max_retries = 3
        retry_delay = 1.0
        last_exc = None

        for attempt in range(max_retries):
            try:
                response = self._get_llm().invoke(prompt)
                return getattr(response, "content", str(response))
            except Exception as exc:
                last_exc = exc
                err_str = str(exc).lower()
                if (
                    "104" in err_str
                    or "reset" in err_str
                    or "time" in err_str
                    or "deadline" in err_str
                ):
                    logger.warning(
                        "GigaChat connection issue (attempt %d/%d), retrying in %.1fs... Error: %s",
                        attempt + 1,
                        max_retries,
                        retry_delay,
                        err_str,
                    )
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                raise exc

        logger.error(
            "Failed to generate answer after %d attempts. Last error: %s", max_retries, last_exc
        )
        return f"Не удалось вызвать LLM для генеративного ответа: {last_exc}"

    def check_health(self) -> dict:
        """Проверяет доступность API GigaChat."""
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
    """
    Фабричный метод для создания генератора ответов.
    :param settings: Объект настроек.
    """
    if settings.llm_provider.lower() == "gigachat":
        logger.info("Building GigaChat answer generator")
        return GigaChatAnswerGenerator(settings)
    logger.info("Building stub answer generator")
    return StubAnswerGenerator()
