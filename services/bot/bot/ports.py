from typing import Protocol


class BotInterface(Protocol):
    def send_message(self, text: str) -> None: ...

    def receive_message(self) -> str: ...
