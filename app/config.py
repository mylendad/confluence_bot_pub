from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    confluence_base_url: str = "https://confluence.example.ru"
    confluence_page_url: str | None = None
    confluence_space_key: str = "TEAM"
    confluence_root_page_id: str | None = None
    confluence_auth_type: str = "auto"
    confluence_username: str | None = None
    confluence_token: str | None = None
    confluence_api_token: str | None = None
    confluence_verify_ssl: bool = True
    confluence_request_delay: float = 0.0
    confluence_user_agent: str | None = None
    confluence_cookie_file: str | None = None


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
    def confluence_auth_token(self) -> str | None:
        return self.confluence_token or self.confluence_api_token

    @model_validator(mode="after")
    def populate_confluence_from_page_url(self) -> "Settings":
        if not self.confluence_page_url:
            return self

        parsed = urlparse(self.confluence_page_url)
        if parsed.scheme and parsed.netloc:
            self.confluence_base_url = f"{parsed.scheme}://{parsed.netloc}"

        page_id = parse_qs(parsed.query).get("pageId", [None])[0]
        if page_id:
            self.confluence_root_page_id = page_id
        return self

    @property
    def gigachat_auth_key(self) -> str | None:
        return self.gigachat_credentials or self.gigachat_api_key or self.gigachat_api_pers


@lru_cache
def get_settings() -> Settings:
    return Settings()
