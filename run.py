from pathlib import Path
from tempfile import TemporaryDirectory

from engine.config import bootstrap_directories
from engine.config import settings
from engine.database import get_database_manager
from engine.filesystem import TransactionEngine
from engine.hashing import HashEngine, HashService
from engine.indexer import IndexerService
from engine.logging import configure, get_logger
from engine.pipeline import QueueManager
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

    scanner_manager = ScannerManager().initialize()
    with TemporaryDirectory(prefix="scanner-self-test-", dir=Path.cwd()) as tmp_dir:
        scan_root = Path(tmp_dir)
        discovered = list(scanner_manager.scan(root=scan_root))
        if discovered == []:
            print("Recursive Scanner OK")

    indexer_service = IndexerService()
    indexer_service.index_paths([Path.cwd()])
    print("Incremental Indexer OK")

    queue_manager = QueueManager()
    hash_service = HashService(queue_manager=queue_manager)
    _ = hash_service  # confirms construction without errors
    print("Hash Engine OK")

    print(settings.app_name)
    print(settings.version)
    print("Configuration OK")
    print("Logging OK")
    print("Database OK")
    print("Transaction Engine initialized")
    print("Service Layer OK")
    print("Scanner Foundation OK")
    print("Pipeline Queue OK")


if __name__ == "__main__":
    main()
