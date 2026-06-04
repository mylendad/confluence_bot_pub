from pydantic import BaseModel, Field


class RAGDocument(BaseModel):
    """
    Модель документа для RAG-системы.
    """
    id: str
    text: str
    metadata: dict = Field(default_factory=dict)


class RetrievedDocument(BaseModel):
    """
    Модель извлеченного документа с оценкой релевантности.
    """
    document: RAGDocument
    score: float


class RAGAnswer(BaseModel):
    """
    Модель ответа RAG-системы, содержащая текст ответа и источники.
    """
    answer: str
    sources: list[dict] = Field(default_factory=list)
