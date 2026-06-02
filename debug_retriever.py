import json
from app.rag.retriever import RAGRetriever
from app.storage.metadata_repository import MetadataRepository
from app.storage.sqlite import SQLite
from pathlib import Path

class MockMetadataRepo:
    def list_datamarts(self):
        return [
            {"name": "Витрина Дети и Родители", "facts_json": json.dumps([
                {"key": "data_location", "label": "Расположение данных", "value": "HDFS /data/children"},
                {"key": "data_category", "label": "Категория данных", "value": "Публичные"}
            ])},
            {"name": "Витрина Маркеры", "facts_json": "[]"}
        ]
    def list_attributes(self, datamart_name=None): return []
    def find_attribute_usage(self, token): return []

repo = MockMetadataRepo()
retriever = RAGRetriever(repo, None, None)

questions = [
    "расположение данных Витрина Дети и Родители",
    "место публикации данных Витрина Дети и Родители",
    "категория данных Витрина Дети и Родители",
    "расположение данных Дети и Родители"
]

for q in questions:
    print(f"\nQuestion: {q}")
    intent = retriever.intent_classifier.classify(q)
    print(f"Intent: {intent}")
    ans = retriever.answer(q)
    print(f"Answer: {ans.answer}")
