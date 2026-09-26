from __future__ import annotations

from pathlib import Path

import pytest

from engine.config import settings
from engine.database.database import database_manager
from engine.embeddings import CLIPProvider, EmbeddingService
from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.recognition import RecognitionService
from engine.recognition.recognition_exceptions import RecognitionProviderError
from engine.runtime import ApplicationHost


@pytest.fixture()
def provider_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "workspace", tmp_path)
    monkeypatch.setattr(settings, "database_directory", Path("database"))
    database_manager._engine = None
    database_manager._session_factory = None
    database_manager._initialized = False
    database_manager.__init__()


def test_embedding_service_defaults_to_real_clip_without_loading_it(provider_env: None) -> None:
    service = EmbeddingService()

    assert isinstance(service.provider, CLIPProvider)
    assert service.provider.model_name == "openai/clip-vit-base-patch32"


def test_recognition_service_rejects_unconfigured_inference(provider_env: None) -> None:
    service = RecognitionService(queue_manager=QueueManager())
    job = PipelineJob(source_path="image.png", queue_type=QueueType.RECOGNITION)

    with pytest.raises(RecognitionProviderError, match="No concrete recognition provider"):
        service.process_recognition_job(job)


def test_application_host_disables_unconfigured_recognition_pipeline(provider_env: None) -> None:
    host = ApplicationHost()
    try:
        assert host.services.recognition.provider is None
        assert host.services.embedding.publish_recognition is False
        assert QueueType.RECOGNITION not in host.workers
        host.start()
    finally:
        host.shutdown()