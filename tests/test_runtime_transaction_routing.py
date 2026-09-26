from __future__ import annotations

from types import SimpleNamespace

import pytest

from engine.pipeline import PipelineJob, QueueType
from engine.runtime import ApplicationHost


class _IntegrityService:
    def __init__(self) -> None:
        self.scan_ids: list[str] = []

    def run_full_scan(self, *, scan_id: str):
        self.scan_ids.append(scan_id)
        return {"scan_id": scan_id}


class _MaintenanceService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run_selected_tasks(self, tasks, *, preview: bool, dry_run: bool, job_id: str):
        call = {"tasks": tasks, "preview": preview, "dry_run": dry_run, "job_id": job_id}
        self.calls.append(call)
        return call


class _TransactionEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def move(self, source: str, destination: str) -> bool:
        self.calls.append(("move", source, destination))
        return True


def _host() -> tuple[ApplicationHost, _IntegrityService, _MaintenanceService, _TransactionEngine]:
    integrity = _IntegrityService()
    maintenance = _MaintenanceService()
    transactions = _TransactionEngine()
    host = object.__new__(ApplicationHost)
    host.services = SimpleNamespace(integrity=integrity, maintenance=maintenance, transactions=transactions)
    return host, integrity, maintenance, transactions


def test_routes_integrity_verification_job() -> None:
    host, integrity, _, _ = _host()
    job = PipelineJob(queue_type=QueueType.TRANSACTION, metadata={"kind": "integrity_verification"})

    result = host._route_transaction_job(job)

    assert result == {"scan_id": str(job.id)}
    assert integrity.scan_ids == [str(job.id)]


def test_routes_explicit_filesystem_operation() -> None:
    host, _, _, transactions = _host()
    job = PipelineJob(
        queue_type=QueueType.TRANSACTION,
        source_path="before.png",
        metadata={"operation": "move", "destination_path": "after.png"},
    )

    assert host._route_transaction_job(job) is True
    assert transactions.calls == [("move", "before.png", "after.png")]


def test_routes_explicit_maintenance_tasks() -> None:
    host, _, maintenance, _ = _host()
    job = PipelineJob(
        queue_type=QueueType.TRANSACTION,
        metadata={"kind": "maintenance", "tasks": ["clean_stale_caches"], "dry_run": True},
    )

    host._route_transaction_job(job)

    assert maintenance.calls[0]["tasks"][0].value == "clean_stale_caches"
    assert maintenance.calls[0]["dry_run"] is True


def test_rejects_ambiguous_transaction_job() -> None:
    host, _, _, _ = _host()

    with pytest.raises(ValueError, match="must declare"):
        host._route_transaction_job(PipelineJob(queue_type=QueueType.TRANSACTION, metadata={"kind": "cleanup"}))