from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    confluence_base_url: str = "https://confluence.example.ru"
    confluence_space_key: str = "TEAM"
    confluence_root_page_id: str | None = None
    confluence_username: str | None = None
    confluence_api_token: str | None = None

    datamart_page_pattern: str = "Витрина"
    s2t_section_patterns: str = "s2t,S2T,Source to Target,Source-to-Target"

    data_dir: Path = Path("./data")
    sqlite_db_path: Path = Path("./data/app.db")
    vector_store_dir: Path = Path("./data/vector_store")

    rag_update_cron: str = "0 2 * * *"
    change_history_days: int = 365

    embedding_provider: str = "local"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    llm_provider: str = "gigachat"
    gigachat_credentials: str | None = None
    gigachat_api_key: str | None = None
    gigachat_api_pers: str | None = None
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat"
    gigachat_verify_ssl_certs: bool = False
    gigachat_profanity_check: bool = False

    log_level: str = Field(default="INFO")

    @property
    def s2t_patterns(self) -> list[str]:
        return [item.strip() for item in self.s2t_section_patterns.split(",") if item.strip()]

    @property
    def gigachat_auth_key(self) -> str | None:
        return self.gigachat_credentials or self.gigachat_api_key or self.gigachat_api_pers


@lru_cache
def get_settings() -> Settings:
    return Settings()
