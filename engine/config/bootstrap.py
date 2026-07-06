from pathlib import Path

from engine.config.settings import settings


def bootstrap_directories() -> None:
    directories = [
        settings.database_directory,
        settings.cache_directory,
        settings.log_directory,
        settings.thumbnail_directory,
        settings.embedding_directory,
        settings.knowledge_directory,
        settings.models_directory,
        settings.datasets_directory,
    ]

    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)
