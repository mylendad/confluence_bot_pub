from app.bot.ports import BotInterface


class SberChatAdapter(BotInterface):
    def send_message(self, text: str) -> None:
        raise NotImplementedError(
            "TODO: implement SberChat send_message when API documentation is available"
        )

    def receive_message(self) -> str:
        raise NotImplementedError(
            "TODO: implement SberChat receive_message when API documentation is available"
        )
