import re

from shared.utils.text_utils import fuzzy_contains, normalize_text


class QueryParser:
    def __init__(self, metadata_repo):
        self.metadata_repo = metadata_repo

    def normalize_cx(self, text: str) -> str:
        return text.replace("С", "C").replace("с", "c").replace("Х", "X").replace("х", "x")

    def matches_datamart(
        self, actual_name: str | None, requested_name: str, actual_code: str | None = None
    ) -> bool:
        requested = self.normalize_cx(normalize_text(requested_name))
        actual = self.normalize_cx(normalize_text(actual_name or ""))
        code = normalize_text(actual_code or "")
        return requested in actual or actual in requested or requested == code

    def extract_datamart_name(self, question: str) -> str | None:
        q_norm = normalize_text(question)
        datamarts = self.metadata_repo.list_datamarts()
        names = sorted(
            [dm.get("name") for dm in datamarts if dm.get("name")],
            key=len,
            reverse=True,
        )

        for name in names:
            norm_name = normalize_text(name)
            if not norm_name:
                continue
            if norm_name in q_norm:
                return name
            short_name = re.sub(r"^витрина\s+", "", norm_name).strip()
            if short_name and len(short_name) > 3 and short_name in q_norm:
                return name

        stop_words = [
            "заинтересован", "атрибут", "измен", "релиз", "владелец",
            "ответствен", "ссылка", "мета", "ка фо", "карта данных",
            "смд", "кэ", "имя", "периодич", "глубина", "процесс",
            "рейтинг", "отчет", "отчёт", "бизнес",
        ]
        stop_pattern = "|".join(stop_words)
        patterns = [
            rf"по\s+витрин[еы]\s+(.+?)(?=\s+(?:{stop_pattern})|$)",
            rf"витрина\s+(.+?)(?=\s+(?:{stop_pattern})|$)",
            rf"витрин[еы]\s+(.+?)(?=\s+(?:{stop_pattern})|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, question, flags=re.IGNORECASE)
            if match:
                value = match.group(1).strip(" ?:.,;\"'")
                value = re.sub(r"\s+с\s+датами$", "", value, flags=re.IGNORECASE).strip()
                if value and value.lower() not in {"за год", "за последний год", "изменения"}:
                    if pattern.startswith("витрина") and not value.lower().startswith("витрина"):
                        return f"Витрина {value}"
                    return value

        words = question.split()
        if words:
            last_word = words[-1].strip(" ?:.,;\"'")
            if len(last_word) > 4 and last_word.lower() not in {"бизнеса", "лица", "лицо"}:
                for name in names:
                    if fuzzy_contains(name, [last_word], threshold=0.85):
                        return name
        return None

    def extract_attribute_name(self, question: str) -> str | None:
        q = question.replace("?", " ").replace("!", " ").replace('"', " ").replace("'", " ")
        tokens = q.split()
        for token in reversed(tokens):
            token = token.strip(" .,;:'`()[]{}")
            if not token:
                continue
            if "_" in token or token.isidentifier():
                if len(token) > 2:
                    return token
        return None

    def attrs_from_question(self, question: str):
        for token in reversed(question.replace("?", " ").replace('"', " ").split()):
            token = token.strip(" .,;:'`()[]{}")
            if "_" in token or token.isidentifier():
                attrs = self.metadata_repo.find_attribute_usage(token)
                if attrs:
                    return attrs
        return []

    def datamarts_from_question(self, question: str) -> list[dict]:
        datamarts = self.metadata_repo.list_datamarts()
        requested_datamart = self.extract_datamart_name(question)
        if not requested_datamart:
            q = normalize_text(question)
            is_broad = any(w in q for w in ["все", "список", "какие", "каждый", "каждой"])

            if "витрин" in q and not is_broad:
                if any(w in q for w in ["какие", "есть", "список"]):
                    return datamarts
                return []

            is_specific = any(
                p in q
                for p in [
                    "заинтересован", "владелец", "ответствен", "релиз", "измен",
                    "атрибут", "расположение", "место публикации", "категория данных",
                ]
            )
            if is_specific and not is_broad:
                return []

            if is_broad:
                return datamarts

            return []
        return [
            dm for dm in datamarts
            if self.matches_datamart(dm.get("name"), requested_datamart, dm.get("code"))
        ]
