import hashlib
import json


class HashService:
    """
    Сервис для вычисления хэш-сумм данных и метаданных.
    Используется для определения изменений в контенте и метаданных.
    """

    @staticmethod
    def sha256_bytes(content: bytes) -> str:
        """
        Вычисляет SHA256 хэш для бинарного содержимого.
        :param content: Бинарные данные.
        :return: Строка с хэшем в формате hex.
        """
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def stable_metadata_hash(metadata: dict) -> str:
        """
        Вычисляет стабильный хэш для словаря метаданных.
        Словарь сериализуется в JSON с сортировкой ключей.
        :param metadata: Словарь метаданных.
        :return: Строка с хэшем в формате hex.
        """
        payload = json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
