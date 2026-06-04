import logging
from collections import deque


class MemoryLogHandler(logging.Handler):
    def __init__(self, maxlen: int = 1000) -> None:
        super().__init__()
        self.logs = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        self.logs.append(msg)

    def get_logs(self) -> list[str]:
        return list(self.logs)


class ColoredFormatter(logging.Formatter):
    """Custom log formatter to add colors based on log level."""
    
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
        color = self.COLORS.get(record.levelno, self.RESET)
        format_str = f"{self.GREY}%(asctime)s{self.RESET} {color}%(levelname)s{self.RESET} [{self.GREY}%(name)s{self.RESET}] %(message)s"
        formatter = logging.Formatter(format_str)
        return formatter.format(record)


memory_handler = MemoryLogHandler()


def configure_logging(level: str = "INFO") -> None:
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
