import logging
import math
import re
from collections import Counter

from shared.utils.text_utils import normalize_text

logger = logging.getLogger(__name__)


class LocalTextEmbedder:
    """
    Лёгкий эмбеддер на основе частот токенов (TF-подобный) без внешних зависимостей.
    Используется как fallback, если sentence-transformers недоступны.
    """

    def embed(self, text: str) -> Counter[str]:
        """
        Преобразует текст в вектор частот токенов.
        :param text: Входной текст для эмбеддинга.
        :return: Counter с частотами токенов.
        """
        return Counter(re.findall(r"[\wА-Яа-яЁё]+", normalize_text(text)))

    def similarity(self, left: str, right: str) -> float:
        """
        Вычисляет косинусное сходство между двумя текстами.
        :param left: Первый текст.
        :param right: Второй текст.
        :return: Значение сходства от 0.0 до 1.0.
        """
        a = self.embed(left)
        b = self.embed(right)
        if not a or not b:
            return 0.0
        dot = sum(a[token] * b[token] for token in a.keys() & b.keys())
        norm_a = math.sqrt(sum(value * value for value in a.values()))
        norm_b = math.sqrt(sum(value * value for value in b.values()))
        return dot / (norm_a * norm_b)


class SentenceTransformerEmbedder:
    """
    Эмбеддер текстов на базе модели sentence-transformers.
    Поддерживает русский и английский языки, вычисляет семантические векторы.
    """

    def __init__(self, model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2") -> None:
        """
        Инициализирует эмбеддер и загружает модель.
        :param model_name: Название модели из Hugging Face Hub.
        """
        try:
            from sentence_transformers import SentenceTransformer

            logger.info("Загрузка модели эмбеддингов: %s", model_name)
            self.model = SentenceTransformer(model_name)
            self.model_name = model_name
            logger.info("Модель эмбеддингов загружена успешно.")
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers не установлен. "
                "Установите: pip install -e '.[rag]'"
            ) from exc

    def embed(self, text: str) -> list[float]:
        """
        Возвращает эмбеддинг текста как список float.
        :param text: Входной текст.
        :return: Вектор эмбеддинга.
        """
        return self.model.encode(text, convert_to_tensor=False).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Вычисляет эмбеддинги для пакета текстов (быстрее, чем по одному).
        :param texts: Список текстов.
        :return: Список векторов эмбеддинга.
        """
        return self.model.encode(texts, convert_to_tensor=False, show_progress_bar=False).tolist()


def build_embedder(provider: str = "local", model_name: str | None = None) -> LocalTextEmbedder | SentenceTransformerEmbedder:
    """
    Фабричная функция для создания эмбеддера в зависимости от настроек.
    :param provider: "local" — TF-подобный без зависимостей, "sentence_transformers" — нейронный.
    :param model_name: Название модели (только для sentence_transformers).
    :return: Экземпляр эмбеддера.
    """
    if provider == "sentence_transformers":
        return SentenceTransformerEmbedder(
            model_name=model_name or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
    return LocalTextEmbedder()
