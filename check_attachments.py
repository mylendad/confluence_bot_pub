import os
import asyncio
from app.config import get_settings
from app.confluence.client import ConfluenceClient

settings = get_settings()
client = ConfluenceClient(settings)

print(f"Fetching attachments for page 17281847916...")
try:
    attachments = client.get_attachments("17281847916")
    print(f"Found {len(attachments)} attachments.")
    for att in attachments:
        print(f" - ID: {att.id}")
        print(f"   Title: {att.title}")
        print(f"   File Name: {att.file_name}")
except Exception as e:
    print(f"Error: {e}")
