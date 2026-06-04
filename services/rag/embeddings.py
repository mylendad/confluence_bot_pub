import math
import re
from collections import Counter

from shared.utils.text_utils import normalize_text


class LocalTextEmbedder:
    """
    Легковесный эмбеддер текстов без внешних зависимостей.
    Основан на частоте токенов и косинусном сходстве.
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
