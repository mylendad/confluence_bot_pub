import logging
from pathlib import Path
from app.config import get_settings
from app.confluence.client import ConfluenceClient

logging.basicConfig(level=logging.INFO)

settings = get_settings()
client = ConfluenceClient(settings)

query = "Inner Source"
print(f"Searching for '{query}'...")
for page in client.search_pages(f'text ~ "{query}"'):
    print(f"Found page: '{page.title}' (ID: {page.id}, URL: {page.url})")
    # Try to find parent
    try:
        # The Confluence V1 API 'content' response often has a 'ancestors' field if expanded
        # but our get_page doesn't expand ancestors.
        # Let's just print the page for now.
        pass
    except Exception:
        pass
