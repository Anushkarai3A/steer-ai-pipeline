from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> parents[3] == repository root
REPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_DIR = REPO_ROOT / "pipeline"
PROMPTS_DIR = PIPELINE_DIR / "prompts"
SCHEMAS_DIR = PIPELINE_DIR / "schemas"
TEMPLATES_DIR = PIPELINE_DIR / "templates"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Steer Research Studio"
    environment: str = "development"
    debug: bool = True

    database_url: str = f"sqlite:///{REPO_ROOT / 'backend' / 'steer.db'}"

    upload_dir: str = str(REPO_ROOT / "data" / "uploads")
    generated_dir: str = str(REPO_ROOT / "data" / "generated")

    secret_key: str = "dev-only-insecure-secret-change-me"
    access_token_ttl_seconds: int = 60 * 60 * 12

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    max_upload_bytes: int = 25 * 1024 * 1024
    allowed_upload_extensions: tuple[str, ...] = (".pdf",)
    min_sources_per_project: int = 1
    max_sources_per_project: int = 3

    llm_provider: str = "none"  # none | openai
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: int = 60

    reel_fps: int = 24
    carousel_max_slides: int = 8

    pipeline_version: str = "1.0.0"

    @property
    def upload_path(self) -> Path:
        p = Path(self.upload_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def generated_path(self) -> Path:
        p = Path(self.generated_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def ai_enabled(self) -> bool:
        return self.llm_provider.lower() in {"openai", "azure", "compatible"} and bool(self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
