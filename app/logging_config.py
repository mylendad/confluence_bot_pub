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


memory_handler = MemoryLogHandler()


def configure_logging(level: str = "INFO") -> None:
    handlers = [logging.StreamHandler(), memory_handler]
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=handlers,
    )
