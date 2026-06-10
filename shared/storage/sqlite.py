import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_local = threading.local()

class SQLite:
    """
    Класс для управления базой данных SQLite, включая инициализацию схемы и управление соединениями.
    """

    def __init__(self, path: Path) -> None:
        """
        Инициализирует объект SQLite и создает базу данных, если она не существует.
        :param path: Путь к файлу базы данных SQLite.
        """
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """
        Глобальный контекстный менеджер (Unit of Work). 
        Гарантирует атомарность серии вызовов connect().
        """
        if hasattr(_local, "conn") and _local.conn is not None:
            yield _local.conn
            return

        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        _local.conn = conn
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            _local.conn = None
            conn.close()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """
        Контекстный менеджер для создания соединения с базой данных.
        Если вызван внутри transaction(), переиспользует текущее соединение.
        """
        if hasattr(_local, "conn") and _local.conn is not None:
            yield _local.conn
            return

        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        """
        Инициализирует схему базы данных с помощью Alembic миграций.
        """
        try:
            from alembic import command
            from alembic.config import Config
            import logging
            
            logger = logging.getLogger(__name__)
            
            base_dir = Path(__file__).parent.parent.parent
            alembic_ini_path = base_dir / "alembic.ini"
            
            if alembic_ini_path.exists():
                alembic_cfg = Config(str(alembic_ini_path))
                alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{self.path.absolute()}")
                command.upgrade(alembic_cfg, "head")
                logger.info("Database schema initialized/updated successfully via Alembic.")
            else:
                logger.warning(f"alembic.ini not found at {alembic_ini_path}. Skipping migrations.")
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to run alembic migrations: {e}")
            raise
