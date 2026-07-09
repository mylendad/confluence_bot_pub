from .chat import router as chat_router
from .data import router as data_router
from .settings import router as settings_router
from .sync import router as sync_router
from .system import router as system_router

__all__ = [
    "chat_router",
    "data_router",
    "settings_router",
    "sync_router",
    "system_router",
]
