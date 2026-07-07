from pathlib import Path
from tempfile import TemporaryDirectory

from engine.config import bootstrap_directories
from engine.config import settings
from engine.database import get_database_manager
from engine.filesystem import TransactionEngine
from engine.hashing import HashEngine, HashService
from engine.duplicates import DuplicateEngine, DuplicateService
from engine.thumbnails import ThumbnailEngine, ThumbnailService
from engine.metadata import MetadataEngine, MetadataService
from engine.embeddings import EmbeddingService
from engine.recognition import RecognitionService
from engine.search import SearchService
from engine.knowledge_graph import KnowledgeGraphService
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

    duplicate_service = DuplicateService(queue_manager=queue_manager)
    _ = duplicate_service
    print("Duplicate Engine OK")

    thumbnail_service = ThumbnailService(queue_manager=queue_manager)
    _ = thumbnail_service
    print("Thumbnail Engine OK")

    metadata_service = MetadataService(queue_manager=queue_manager)
    _ = metadata_service
    print("Metadata Engine OK")

    embedding_service = EmbeddingService(queue_manager=queue_manager)
    _ = embedding_service
    print("Embedding Engine OK")

    recognition_service = RecognitionService(queue_manager=queue_manager)
    _ = recognition_service
    print("Recognition Engine OK")

    search_service = SearchService(queue_manager=queue_manager)
    _ = search_service
    print("Semantic Search Engine OK")

    knowledge_graph_service = KnowledgeGraphService(queue_manager=queue_manager)
    _ = knowledge_graph_service
    print("Knowledge Graph Engine OK")

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
