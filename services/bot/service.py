from services.rag.models import RAGAnswer
from services.rag.retriever import RAGRetriever


class BotService:
    """
    Бизнес-логика бота для взаимодействия с RAG-системой.
    """
    def __init__(self, retriever: RAGRetriever) -> None:
        """
        Инициализирует BotService.
        :param retriever: Объект ретривера для поиска ответов.
        """
        self.retriever = retriever

    def ask(self, question: str) -> RAGAnswer:
        """Задает вопрос RAG-системе и возвращает ответ."""
        return self.retriever.answer(question)

    @staticmethod
    def format_answer(answer: RAGAnswer) -> str:
        """Форматирует ответ RAG-системы для отображения пользователю."""
        if not answer.sources:
            return f"Ответ:\n{answer.answer}"

        # Дедупликация источников перед выводом
        unique_sources = []
        seen = set()
        for s in answer.sources:
            # Используем те же поля, что и при выводе, для определения уникальности
            dm = s.get('datamart') or s.get('datamart_name') or '-'
            s2t = s.get('s2t_file') or s.get('s2t_file_name') or 'нет s2t'
            date = s.get('s2t_file_date') or '-'
            url = s.get('confluence_url') or s.get('source_url') or '-'

            key = (dm, s2t, date, url)
            if key not in seen:
                seen.add(key)
                unique_sources.append(s)

        source_lines = []
        for idx, source in enumerate(unique_sources, start=1):
            s2t_file = source.get('s2t_file') or source.get('s2t_file_name')
            s2t_display = s2t_file if s2t_file else "нет s2t на конфлюенсе"
            source_lines.append(
                f"{idx}. Витрина: {source.get('datamart') or source.get('datamart_name') or '-'}\n"
                f"   S2T: {s2t_display}\n"
                f"   Дата S2T: {source.get('s2t_file_date') or '-'}\n"
                f"   Confluence: {source.get('confluence_url') or source.get('source_url') or '-'}"
            )
        return f"Ответ:\n{answer.answer}\n\nИсточники:\n" + "\n".join(source_lines)
