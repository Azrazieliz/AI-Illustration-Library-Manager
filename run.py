from engine.config import bootstrap_directories
from engine.config import settings
from engine.database import get_database_manager
from engine.filesystem import TransactionEngine
from engine.logging import configure, get_logger
from engine.scanner import ScannerManager
from engine.services import (
    CharacterService,
    ImageService,
    JobService,
    KnowledgeService,
    ReviewService,
    SeriesService,
    TagService,
    TransactionService,
)


def main() -> None:
    bootstrap_directories()
    configure()

    logger = get_logger("run")
    logger.info("Logging initialized")

    manager = get_database_manager()
    manager.initialize()

    TransactionEngine()

    ImageService()
    SeriesService()
    CharacterService()
    TagService()
    JobService()
    TransactionService()
    ReviewService()
    KnowledgeService()

    ScannerManager().initialize()

    print(settings.app_name)
    print(settings.version)
    print("Configuration OK")
    print("Logging OK")
    print("Database OK")
    print("Transaction Engine initialized")
    print("Service Layer OK")
    print("Scanner Foundation OK")


if __name__ == "__main__":
    main()
