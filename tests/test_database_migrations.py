from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from engine.database.database import DatabaseManager
from engine.database.models import Embedding


def test_legacy_embedding_schema_is_upgraded_additively(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.sqlite').resolve()}", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE embedding (
                    id INTEGER NOT NULL,
                    uuid VARCHAR(36) NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    image_id INTEGER NOT NULL,
                    vector_path VARCHAR(2048) NOT NULL,
                    model_name VARCHAR(512) NOT NULL,
                    model_version VARCHAR(128) NOT NULL,
                    PRIMARY KEY (id),
                    UNIQUE (uuid),
                    UNIQUE (image_id),
                    FOREIGN KEY(image_id) REFERENCES image (id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO embedding (
                    id, uuid, created_at, updated_at, image_id, vector_path, model_name, model_version
                ) VALUES (
                    1, '00000000-0000-0000-0000-000000000001', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                    999, 'legacy.npy', 'legacy-model', '1.0'
                )
                """
            )
        )

    manager = DatabaseManager()
    original_engine = manager._engine
    original_session_factory = manager._session_factory
    manager._engine = engine
    manager._session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    try:
        manager.create_tables()
        inspector = inspect(engine)
        assert {
            "advanced_saved_search",
            "advanced_search_history",
            "adaptive_learning_state",
            "ai_execution",
            "automation_job",
            "automation_run",
            "bulk_state",
            "collection",
            "collection_membership",
            "character_database_state",
            "dataset",
            "export_artifact",
            "knowledge_base_state",
            "knowledge_graph_edge",
            "knowledge_graph_node",
            "knowledge_pack_state",
            "maintenance_state",
            "organizer_batch_state",
            "pipeline_job",
            "plugin_runtime",
            "recognition_history",
            "rename_batch_state",
            "review_batch",
            "review_decision",
            "review_queue_item",
            "tag_provenance",
        }.issubset(inspector.get_table_names())
        columns = {column["name"] for column in inspector.get_columns("embedding")}
        assert {
            "image_uuid",
            "dimension",
            "dtype",
            "storage_path",
            "checksum",
            "version",
        }.issubset(columns)
        indexes = {index["name"] for index in inspector.get_indexes("embedding")}
        assert {"ix_embedding_checksum", "ix_embedding_image_uuid"}.issubset(indexes)

        with Session(engine) as session:
            record = session.query(Embedding).one()
            assert record.version == 1
            assert record.image_uuid is None
            assert record.dimension is None
            assert record.dtype is None
            assert record.storage_path is None
            assert record.checksum is None
            record.model_name = "upgraded-model"
            session.commit()
            assert record.version == 2

        manager.create_tables()
        assert {
            "ix_embedding_checksum",
            "ix_embedding_image_uuid",
        }.issubset({index["name"] for index in inspect(engine).get_indexes("embedding")})
    finally:
        manager._engine = original_engine
        manager._session_factory = original_session_factory
        engine.dispose()