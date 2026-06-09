from services.bot.ports import BotInterface


class SberChatAdapter(BotInterface):
    """
    Адаптер для взаимодействия с ботом через SberChat.
    """

    def send_message(self, text: str) -> None:
        """
        Отправляет сообщение в SberChat (не реализовано).
        :param text: Текст сообщения.
        """
        raise NotImplementedError(
            "TODO: implement SberChat send_message when API documentation is available"
        )

    def receive_message(self) -> str:
        """
        Получает сообщение из SberChat (не реализовано).
        :return: Текст полученного сообщения.
        """
        raise NotImplementedError(
            "TODO: implement SberChat receive_message when API documentation is available"
        )
