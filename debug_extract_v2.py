
import re
from app.utils.text_utils import normalize_text

def _extract_datamart_name(question: str) -> str | None:
    stop_words = [
        "заинтересован", "атрибут", "измен", "релиз", "владелец", "ответствен", 
        "ссылка", "мета", "ка фо", "карта", "смд", "кэ", "имя", "периодич", 
        "глубина", "процесс", "рейтинг", "отчет", "отчёт"
    ]
    stop_pattern = "|".join(stop_words)
    
    patterns = [
        rf"по\s+витрин[еы]\s+(.+?)(?=\s+(?:{stop_pattern})|$)",
        rf"витрина\s+(.+?)(?=\s+(?:{stop_pattern})|$)",
        rf"витрин[еы]\s+(.+?)(?=\s+(?:{stop_pattern})|$)",
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
    return None

question = "Витрина Тестирование CX Заинтересованные со стороны бизнеса"
print(f"Question: {question}")
print(f"Extracted: {_extract_datamart_name(question)}")
