from services.bot.api.routers.chat import router as chat_router
from services.bot.api.routers.data import router as data_router
from services.bot.api.routers.settings import router as settings_router
from services.bot.api.routers.sync import router as sync_router
from services.bot.api.routers.system import router as system_router

__all__ = [
    "settings_router",
    "chat_router",
    "sync_router",
    "system_router",
    "data_router"
]
