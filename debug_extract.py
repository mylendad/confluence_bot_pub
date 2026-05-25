
import re
from app.utils.text_utils import normalize_text

def _extract_datamart_name(question: str) -> str | None:
    patterns = [
        r"по\s+витрин[еы]\s+(.+?)(?:\s|$)",
        r"витрина\s+(.+?)(?:\s|$)",
        r"витрин[еы]\s+(.+?)(?:\s|$)",
    ]
    q_norm = normalize_text(question)
    for pattern in patterns:
        match = re.search(pattern, question, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip(" ?:.,;\"'")
            if value and value.lower() not in {"за год", "за последний год", "изменения"}:
                if pattern.startswith("витрина"):
                    return f"Витрина {value}"
                return value

    names = ["Витрина Пакеты услуг CX", "Витрина Маркеры"]
    for name in names:
        if normalize_text(name) in q_norm:
            return name
    return None

def _matches_datamart(actual_name, requested_name):
    requested = normalize_text(requested_name)
    actual = normalize_text(actual_name or "")
    return requested in actual or actual in requested

question = "Витрина Тестирование CX Заинтересованные со стороны бизнеса"
requested = _extract_datamart_name(question)
print(f"Extracted: {requested}")

names = ["Витрина Пакеты услуг CX", "Витрина Маркеры", "Витрина Дети и Родители"]
matching = [n for n in names if _matches_datamart(n, requested)]
print(f"Matching datamarts: {matching}")

if not requested:
    print("Fallback to ALL datamarts")
elif not matching:
    print("No matching datamarts found (would return 'not found')")
else:
    print(f"Found {len(matching)} matching datamarts")
