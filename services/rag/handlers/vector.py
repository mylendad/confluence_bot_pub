from services.rag.handlers.base import BaseHandler
from services.rag.models import RAGAnswer


class VectorAnswerHandler(BaseHandler):
    def handle(self, question: str) -> RAGAnswer | None:
        docs = self.vector_store.search(question, k=5)
        if not docs:
            return RAGAnswer(
                answer="Данных для ответа нет. Сначала распарсьте S2T и соберите RAG.",
                sources=[],
            )
        context = "\n".join(item.document.text for item in docs)
        try:
            answer = self.answer_generator.generate(question, context)
        except Exception as exc:
            answer = f"Не удалось вызвать LLM для генеративного ответа: {exc}"
        return RAGAnswer(
            answer=answer,
            sources=[item.document.metadata for item in docs],
        )
