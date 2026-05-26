import json
from dataclasses import dataclass
from datetime import datetime

from app.storage.sqlite import SQLite


@dataclass(frozen=True)
class ChatMessage:
    session_id: str
    user_message: str
    bot_response: str
    sources: list[str]
    created_at: datetime


class ChatHistoryRepository:
    def __init__(self, db: SQLite) -> None:
        self.db = db

    def add(self, message: ChatMessage) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                insert into chat_history(
                    session_id, user_message, bot_response, sources_json, created_at
                )
                values (?, ?, ?, ?, ?)
                """,
                (
                    message.session_id,
                    message.user_message,
                    message.bot_response,
                    json.dumps(message.sources, ensure_ascii=False),
                    message.created_at.isoformat(),
                ),
            )

    def list_by_session(self, session_id: str) -> list[ChatMessage]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "select * from chat_history where session_id = ? order by created_at asc",
                (session_id,),
            ).fetchall()
        return [
            ChatMessage(
                session_id=row["session_id"],
                user_message=row["user_message"],
                bot_response=row["bot_response"],
                sources=json.loads(row["sources_json"]),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]
