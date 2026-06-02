import asyncio
from app.config import get_settings
from app.confluence.client import ConfluenceClient
import sys

settings = get_settings()
client = ConfluenceClient(settings)

results = client.search_pages('title ~ "inner source"')
for r in results:
    print(f"ID: {r.id}, Title: {r.title}")
