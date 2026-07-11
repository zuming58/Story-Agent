from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def default_data_dir() -> Path:
    return Path(__file__).resolve().parents[4] / ".data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STORY_AGENT_", extra="ignore")

    data_dir: Path = default_data_dir()
    cors_origins: str = "http://127.0.0.1:4173,http://localhost:4173"
    seed_demo: bool = True

    @property
    def catalog_path(self) -> Path:
        return self.data_dir / "catalog.db"

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
