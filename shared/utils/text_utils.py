import re
from difflib import SequenceMatcher


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    # Remove punctuation and special characters, collapse spaces, lowercase
    cleaned = re.sub(r"[^\w\s]", " ", value)
    return re.sub(r"\s+", " ", cleaned.strip().lower())


def fuzzy_contains(text: str, candidates: list[str], threshold: float = 0.78) -> bool:
    normalized = normalize_text(text)
    if any(normalize_text(candidate) in normalized for candidate in candidates):
        return True
    words = normalized.split()
    for candidate in candidates:
        target = normalize_text(candidate)
        for size in range(1, min(4, len(words)) + 1):
            for i in range(0, len(words) - size + 1):
                window = " ".join(words[i : i + size])
                if SequenceMatcher(None, window, target).ratio() >= threshold:
                    return True
    return False
