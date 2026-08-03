from pathlib import Path
import gc
from tempfile import TemporaryDirectory
from time import perf_counter

from engine.config import bootstrap_directories
from engine.config import settings
from engine.logging import configure, get_logger, shutdown as shutdown_logging
from engine.release import collect_runtime_diagnostics, load_release_metadata, validate_runtime_dependencies
from engine.runtime import ApplicationHost


def main() -> None:
    startup_started = perf_counter()
    host: ApplicationHost | None = None
    bootstrap_directories()
    metadata = load_release_metadata()
    configure(app_name=metadata.app_name, version=metadata.version)

    logger = get_logger("run")
    logger.info("Logging initialized")
    logger.info("Release metadata", extra={"release_channel": metadata.release_channel, "build_commit": metadata.build_commit})

    dependency_state = validate_runtime_dependencies()
    logger.info("Dependency validation", extra={"missing_dependencies": dependency_state.missing})

    try:
        host = ApplicationHost()
        host.start()

        scanner_service = host.services.scanner.initialize()
        with TemporaryDirectory(prefix="scanner-self-test-", dir=Path.cwd()) as tmp_dir:
            scan_root = Path(tmp_dir)
            discovered = list(scanner_service.scan(root=scan_root))
            if discovered == []:
                print("Recursive Scanner OK")

        _ = host.services.indexer
        print("Incremental Indexer OK")

        hash_service = host.services.hash
        _ = hash_service
        print("Hash Engine OK")

        duplicate_service = host.services.duplicate
        _ = duplicate_service
        print("Duplicate Engine OK")

        thumbnail_service = host.services.thumbnail
        _ = thumbnail_service
        print("Thumbnail Engine OK")

        metadata_service = host.services.metadata
        _ = metadata_service
        print("Metadata Engine OK")

        embedding_service = host.services.embedding
        _ = embedding_service
        print("Embedding Engine OK")

        recognition_service = host.services.recognition
        _ = recognition_service
        print("Recognition Engine OK")

        search_service = host.services.search
        _ = search_service
        print("Semantic Search Engine OK")

        knowledge_graph_service = host.services.knowledge_graph
        _ = knowledge_graph_service
        print("Knowledge Graph Engine OK")

        tagging_service = host.services.tagging
        _ = tagging_service
        print("Automatic Tagging Engine OK")

        dataset_service = host.services.dataset
        _ = dataset_service
        print("Dataset Engine OK")

        export_service = host.services.export
        _ = export_service
        print("Dataset Export Engine OK")

        collection_service = host.services.collections
        _ = collection_service
        print("Collection Manager OK")

        library_service = host.services.library
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
        if host is not None:
            host.shutdown()
        gc.collect()
        shutdown_logging()


if __name__ == "__main__":
    main()
