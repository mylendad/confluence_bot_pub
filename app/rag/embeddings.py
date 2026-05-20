import math
import re
from collections import Counter

from app.utils.text_utils import normalize_text


class LocalTextEmbedder:
    """Small dependency-free embedding fallback based on token frequencies."""

    def embed(self, text: str) -> Counter[str]:
        return Counter(re.findall(r"[\wА-Яа-яЁё]+", normalize_text(text)))

    def similarity(self, left: str, right: str) -> float:
        a = self.embed(left)
        b = self.embed(right)
        if not a or not b:
            return 0.0
        dot = sum(a[token] * b[token] for token in a.keys() & b.keys())
        norm_a = math.sqrt(sum(value * value for value in a.values()))
        norm_b = math.sqrt(sum(value * value for value in b.values()))
        return dot / (norm_a * norm_b)
