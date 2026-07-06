from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AILM_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "AI Illustration Library Manager"
    version: str = "0.1.0"

    workspace: Path = Path.cwd()

    database_directory: Path = Field(default=Path("database"))

    cache_directory: Path = Field(default=Path("cache"))

    log_directory: Path = Field(default=Path("logs"))

    thumbnail_directory: Path = Field(default=Path("cache/thumbnails"))

    embedding_directory: Path = Field(default=Path("cache/embeddings"))

    knowledge_directory: Path = Field(default=Path("knowledge_base"))

    models_directory: Path = Field(default=Path("models"))

    datasets_directory: Path = Field(default=Path("datasets"))

    max_background_workers: int = 4

    auto_save_interval: int = 60

    transaction_history_limit: int = 10000


settings = Settings()
