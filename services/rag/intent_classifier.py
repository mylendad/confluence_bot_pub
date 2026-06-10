from shared.utils.text_utils import normalize_text


class IntentClassifier:
    """
    Классификатор намерений пользователя на основе текста вопроса.
    """

    def classify(self, question: str) -> str:
        q = normalize_text(question)

        if "измен" in q and any(
            word in q for word in ["период", "дата", "датам", "история", "текущ"]
        ):
            if "релиз" not in q:
                return "last_year_changes"

        if (
            "релиз" in q
            or (
                "измен" in q
                and any(word in q for word in ["год", "последн", "поледн", "послед", "свеж", "нов"])
            )
            or ("измен" in q and ("витрин" in q or "март" in q))
        ):
            return "release_changes"

        if any(
            phrase in q
            for phrase in [
                "заинтересованные со стороны бизнеса",
                "заинтересованные лица",
                "заинтересованное лицо",
                "ссылка на мета",
                "ка фо",
                "карта данных",
                "смд",
                "кэ",
                "имя витрины в бд",
                "витрина в бд",
                "периодичность",
                "глубина",
                "процесс из реестра",
                "зарегистрированных процессов",
                "зарегестрированных процессов",
                "расположение данных",
                "место публикации",
                "категория данных",
            ]
        ):
            return "datamart_fact"

        if any(word in q for word in ["владелец", "ответствен"]):
            return "owner_lookup"
        if "заинтересован" in q:
            if any(p in q for p in ["бизнес", "лиц", "сторон"]):
                return "datamart_fact"
            if "витрин" in q:
                return "datamart_fact"
            return "owner_lookup"
        if "атрибутный состав" in q or "какие атрибут" in q or "атрибуты" in q:
            return "attribute_composition"
        if ("в каких витринах" in q or "где есть" in q) and any(
            c in q for c in ["epk_id", "_id", "_dt", "_cd"]
        ):
            return "attribute_usage"
        if any(word in q for word in ["источник", "lineage", "откуда"]):
            return "source_lineage"
        if any(word in q for word in ["логика", "преобразован", "расчет", "расчёт"]):
            return "transformation_logic"

        if (
            "витрин" in q
            and any(word in q for word in ["какие", "список", "есть"])
            and not any(
                word in q
                for word in ["атрибут", "измен", "релиз", "epk_id", "_id", "источник", "логика"]
            )
        ):
            return "datamart_list"

        return "general_question"
