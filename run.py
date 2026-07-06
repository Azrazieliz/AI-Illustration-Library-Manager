from engine.config import bootstrap_directories
from engine.config import settings
from engine.database import get_database_manager
from engine.filesystem import TransactionEngine
from engine.logging import configure, get_logger


def main() -> None:
    bootstrap_directories()
    configure()

    logger = get_logger("run")
    logger.info("Logging initialized")

    manager = get_database_manager()
    manager.initialize()

    TransactionEngine()

    print(settings.app_name)
    print(settings.version)
    print("Configuration OK")
    print("Logging OK")
    print("Database OK")
    print("Transaction Engine initialized")


if __name__ == "__main__":
    main()
