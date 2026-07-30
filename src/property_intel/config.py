from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProvider = Literal["openai", "gemini", "grok", "groq"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: LLMProvider = "gemini"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_api_base: str = ""

    google_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    xai_api_key: str = ""
    grok_model: str = "grok-2-1212"

    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"

    database_url: str = (
        "postgresql+psycopg://property_intel:property_intel@localhost:5433/property_intel"
    )
    chroma_path: str = "./data/chroma"
    raw_data_dir: str = "./data/raw"
    crawl_urls_file: str = "./data/crawl/urls.txt"
    crawl_search_urls_file: str = "./data/crawl/search_urls.txt"
    firecrawl_api_key: str = ""
    firecrawl_api_base: str = "https://api.firecrawl.dev"
    crawl_rate_limit_seconds: float = 2.0
    crawl_max_body_chars: int = 8000
    extract_max_body_chars: int = 2500
    extract_rate_limit_seconds: float = 8.0
    extract_max_retries: int = 4
    extract_enable_llm_summary: bool = True
    chat_search_top_k: int = 15
    search_max_age_days: int = 7

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")

    @property
    def chroma_path_resolved(self) -> Path:
        return Path(self.chroma_path).resolve()

    @property
    def raw_data_dir_resolved(self) -> Path:
        return Path(self.raw_data_dir).resolve()

    @property
    def crawl_urls_file_resolved(self) -> Path:
        return Path(self.crawl_urls_file).resolve()

    @property
    def crawl_search_urls_file_resolved(self) -> Path:
        return Path(self.crawl_search_urls_file).resolve()

    @property
    def database_path_resolved(self) -> Path:
        if not self.is_sqlite:
            raise ValueError("database_path_resolved is only valid for SQLite URLs")
        url = self.database_url.removeprefix("sqlite:///")
        return Path(url).resolve()

    def has_llm_credentials(self) -> bool:
        if self.llm_provider == "openai":
            if self.openai_api_base.strip():
                return True
            return bool(self.openai_api_key.strip())
        if self.llm_provider == "gemini":
            return bool(self.google_api_key.strip())
        if self.llm_provider == "grok":
            return bool(self.xai_api_key.strip())
        if self.llm_provider == "groq":
            return bool(self.groq_api_key.strip())
        return False


@lru_cache
def get_settings() -> Settings:
    return Settings()
