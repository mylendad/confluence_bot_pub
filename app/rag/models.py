from pydantic import BaseModel, Field


class RAGDocument(BaseModel):
    id: str
    text: str
    metadata: dict = Field(default_factory=dict)


class RetrievedDocument(BaseModel):
    document: RAGDocument
    score: float


class RAGAnswer(BaseModel):
    answer: str
    sources: list[dict] = Field(default_factory=list)
