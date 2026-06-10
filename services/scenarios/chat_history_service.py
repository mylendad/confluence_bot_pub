from shared.factory import build_chat_history_repository


class ChatHistoryService:
    def clear_history(self, session_id: str) -> None:
        repo = build_chat_history_repository()
        with repo.db.connect() as conn:
            conn.execute("DELETE FROM chat_history WHERE session_id = ?", (session_id,))
