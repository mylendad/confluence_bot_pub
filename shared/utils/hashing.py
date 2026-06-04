import hashlib
import json
from typing import Any


def stable_hash(value: Any) -> str:
    """
    Вычисляет стабильный SHA-256 хеш для любого объекта, преобразуемого в JSON.
    :param value: Объект для хеширования.
    :return: Строка с шестнадцатеричным представлением хеша.
    """
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
