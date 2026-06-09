from typing import Protocol


class BotInterface(Protocol):
    """
    Интерфейс для взаимодействия с ботом.
    Определяет методы для отправки и получения сообщений.
    """

    def send_message(self, text: str) -> None:
        """
        Отправляет текстовое сообщение пользователю.
        :param text: Текст сообщения.
        """
        ...

    def receive_message(self) -> str:
        """
        Ожидает и получает текстовое сообщение от пользователя.
        :return: Текст полученного сообщения.
        """
        ...
