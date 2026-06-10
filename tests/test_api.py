import pytest
from fastapi.testclient import TestClient

from services.bot.main import app
from services.bot.http_adapter import AskResponse

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_questions_templates():
    response = client.get("/api/questions/templates")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert "owner" in [t["id"] for t in data]

def test_clear_chat_history_requires_session_id():
    response = client.post("/api/clear-chat-history", json={})
    assert response.status_code == 400

def test_save_tokens_is_forbidden():
    response = client.post("/api/save-tokens", json={"confluence_token": "test"})
    assert response.status_code == 403
    assert "безопасности" in response.json()["detail"]

def test_clear_tokens_is_forbidden():
    response = client.post("/api/clear-tokens")
    assert response.status_code == 403
    assert "безопасности" in response.json()["detail"]

def test_interrupt_update_is_not_implemented():
    response = client.post("/api/interrupt-update")
    # Will be 501 or message that it's not running depending on state, 
    # but since it's not running, it returns 200 with "already finished" or 501.
    # Current behavior: if not running, returns 200. Let's check:
    assert response.status_code == 200
    assert "не найден" in response.json()["message"]
