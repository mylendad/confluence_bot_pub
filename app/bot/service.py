from app.rag.models import RAGAnswer
from app.rag.retriever import RAGRetriever


class BotService:
    def __init__(self, retriever: RAGRetriever) -> None:
        self.retriever = retriever

    def ask(self, question: str) -> RAGAnswer:
        return self.retriever.answer(question)

    @staticmethod
    def format_answer(answer: RAGAnswer) -> str:
        if not answer.sources:
            return f"Ответ:\n{answer.answer}"
        source_lines = []
        for idx, source in enumerate(answer.sources, start=1):
            source_lines.append(
                f"{idx}. Витрина: {source.get('datamart') or source.get('datamart_name') or '-'}\n"
                f"   S2T: {source.get('s2t_file') or source.get('s2t_file_name') or '-'}\n"
                f"   Дата S2T: {source.get('s2t_file_date') or '-'}\n"
                f"   Confluence: {source.get('confluence_url') or source.get('source_url') or '-'}"
            )
        return f"Ответ:\n{answer.answer}\n\nИсточники:\n" + "\n".join(source_lines)
