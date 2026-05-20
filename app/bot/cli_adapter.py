from app.bot.ports import BotInterface


class CLIAdapter(BotInterface):
    def send_message(self, text: str) -> None:
        print(text)

    def receive_message(self) -> str:
        return input("> ")
