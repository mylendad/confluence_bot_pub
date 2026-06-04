from services.bot.ports import BotInterface


class CLIAdapter(BotInterface):
    """
    Адаптер для взаимодействия с ботом через командную строку (CLI).
    """
    def send_message(self, text: str) -> None:
        """
        Выводит текстовое сообщение в консоль.
        :param text: Текст сообщения.
        """
        print(text)

    def receive_message(self) -> str:
        """
        Ожидает ввод пользователя из консоли.
        :return: Строка, введенная пользователем.
        """
        return input("> ")
