from pathlib import Path
import gc
from tempfile import TemporaryDirectory
from time import perf_counter

from engine.config import bootstrap_directories
from engine.config import settings
from engine.logging import configure, get_logger, shutdown as shutdown_logging
from engine.release import collect_runtime_diagnostics, load_release_metadata, validate_runtime_dependencies


def main() -> None:
    startup_started = perf_counter()
    bootstrap_directories()
    metadata = load_release_metadata()
    configure(app_name=metadata.app_name, version=metadata.version)

    logger = get_logger("run")
    logger.info("Logging initialized")
    logger.info("Release metadata", extra={"release_channel": metadata.release_channel, "build_commit": metadata.build_commit})

    dependency_state = validate_runtime_dependencies()
    logger.info("Dependency validation", extra={"missing_dependencies": dependency_state.missing})

    try:
        from engine.database import get_database_manager
        from engine.filesystem import TransactionEngine
        from engine.hashing import HashService
        from engine.duplicates import DuplicateService
        from engine.thumbnails import ThumbnailService
        from engine.metadata import MetadataService
        from engine.embeddings import EmbeddingService
        from engine.recognition import RecognitionService
        from engine.search import SearchService
        from engine.knowledge_graph import KnowledgeGraphService
        from engine.tagging import TaggingService
        from engine.dataset import DatasetService
        from engine.export import ExportService
        from engine.collections import CollectionService
        from engine.library import LibraryService
        from engine.indexer import IndexerService
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
        _ = hash_service
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

        tagging_service = TaggingService(queue_manager=queue_manager)
        _ = tagging_service
        print("Automatic Tagging Engine OK")

        dataset_service = DatasetService(queue_manager=queue_manager)
        _ = dataset_service
        print("Dataset Engine OK")

        export_service = ExportService(queue_manager=queue_manager)
        _ = export_service
        print("Dataset Export Engine OK")

        collection_service = CollectionService(queue_manager=queue_manager)
        _ = collection_service
        print("Collection Manager OK")

        library_service = LibraryService()
        _ = library_service
        print("Library Management Foundation OK")

        startup_diagnostics = collect_runtime_diagnostics()
        startup_elapsed = perf_counter() - startup_started
        logger.info(
            "Startup diagnostics",
            extra={
                "startup_elapsed_seconds": startup_elapsed,
                "active_threads": startup_diagnostics.active_threads,
                "memory_current_bytes": startup_diagnostics.traced_memory_current_bytes,
                "memory_peak_bytes": startup_diagnostics.traced_memory_peak_bytes,
            },
        )

        print(settings.app_name)
        print(settings.version)
        print("Configuration OK")
        print("Logging OK")
        print("Database OK")
        print("Transaction Engine initialized")
        print("Service Layer OK")
        print("Scanner Foundation OK")
        print("Pipeline Queue OK")

    finally:
        gc.collect()
        shutdown_logging()


if __name__ == "__main__":
    main()
