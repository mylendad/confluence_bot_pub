import logging
from collections import deque


class MemoryLogHandler(logging.Handler):
    """
    Обработчик логов, сохраняющий последние записи в оперативной памяти (в очереди с ограниченным размером).
    """
    def __init__(self, maxlen: int = 1000) -> None:
        """
        Инициализирует MemoryLogHandler.
        :param maxlen: Максимальное количество сохраняемых записей логов.
        """
        super().__init__()
        self.logs = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        """
        Форматирует и добавляет запись лога в очередь.
        :param record: Объект записи лога.
        """
        msg = self.format(record)
        self.logs.append(msg)

    def get_logs(self) -> list[str]:
        """
        Возвращает список всех накопленных логов.
        :return: Список строк логов.
        """
        return list(self.logs)


class ColoredFormatter(logging.Formatter):
    """
    Пользовательский форматтер логов, добавляющий цвета в зависимости от уровня важности.
    """
    
    # ANSI escape codes
    GREY = "\x1b[38;20m"
    YELLOW = "\x1b[33;20m"
    RED = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    CYAN = "\x1b[36;20m"
    RESET = "\x1b[0m"
    
    COLORS = {
        logging.DEBUG: GREY,
        logging.INFO: CYAN,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: BOLD_RED,
    }

    def format(self, record):
        """
        Форматирует запись лога с использованием ANSI-цветов.
        :param record: Объект записи лога.
        :return: Отформатированная строка лога.
        """
        color = self.COLORS.get(record.levelno, self.RESET)
        format_str = f"{self.GREY}%(asctime)s{self.RESET} {color}%(levelname)s{self.RESET} [{self.GREY}%(name)s{self.RESET}] %(message)s"
        formatter = logging.Formatter(format_str)
        return formatter.format(record)


memory_handler = MemoryLogHandler()


def configure_logging(level: str = "INFO") -> None:
    """
    Настраивает систему логирования приложения.
    :param level: Уровень логирования (например, 'INFO', 'DEBUG').
    """
    # Set standard format for memory handler (plain text)
    memory_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    
    # Set colored format for console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(ColoredFormatter())
    
    handlers = [console_handler, memory_handler]
    
    # We use basicConfig but manage handlers explicitly to avoid duplicates
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Clear existing handlers to prevent duplicate output during re-config
    if root.hasHandlers():
        root.handlers.clear()
        
    for handler in handlers:
        root.addHandler(handler)
