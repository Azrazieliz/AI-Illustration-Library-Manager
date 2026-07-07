from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from engine.automation import (
    AutomationCondition,
    AutomationEngine,
    AutomationRetryPolicy,
    AutomationScheduleType,
    AutomationService,
    AutomationTriggerType,
    AutomationWorker,
)
from engine.automation.automation_exceptions import AutomationValidationError
from engine.pipeline import PipelineJob, QueueType


def _new_engine() -> AutomationEngine:
    return AutomationEngine()


def test_one_shot_and_delayed_schedule() -> None:
    engine = _new_engine()
    now = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

    one_shot = engine.schedule_job(
        job_id="one-shot",
        name="One Shot",
        action="scan",
        queue_type=QueueType.DISCOVERY,
        priority=5,
        schedule_type=AutomationScheduleType.ONE_SHOT,
        trigger_type=AutomationTriggerType.SCHEDULED,
        run_at=now,
    )
    delayed = engine.schedule_delayed_job(
        job_id="delayed",
        name="Delayed",
        action="metadata",
        queue_type=QueueType.METADATA,
        priority=1,
        delay_seconds=30,
    )

    assert one_shot.next_run_at == now
    assert delayed.next_run_at is not None
    assert delayed.next_run_at > now


def test_recurring_and_cron_next_run_changes_after_execution() -> None:
    engine = _new_engine()
    now = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

    recurring = engine.schedule_job(
        job_id="recurring",
        name="Recurring",
        action="reindex",
        queue_type=QueueType.INDEX,
        priority=10,
        schedule_type=AutomationScheduleType.RECURRING,
        trigger_type=AutomationTriggerType.SCHEDULED,
        interval_seconds=60,
    )
    cron = engine.schedule_job(
        job_id="cron",
        name="Cron",
        action="hash",
        queue_type=QueueType.HASH,
        priority=9,
        schedule_type=AutomationScheduleType.CRON,
        trigger_type=AutomationTriggerType.SCHEDULED,
        cron_expression="*/5 * * * *",
    )

    engine.repository.update_job_fields("recurring", next_run_at=now - timedelta(seconds=1))
    engine.repository.update_job_fields("cron", next_run_at=now - timedelta(seconds=1))

    runs = engine.run_due(now=now)
    assert len(runs) == 2

    recurring_after = engine.repository.get_job("recurring")
    cron_after = engine.repository.get_job("cron")
    assert recurring_after is not None and recurring_after.next_run_at is not None
    assert cron_after is not None and cron_after.next_run_at is not None
    assert recurring_after.next_run_at > now
    assert cron_after.next_run_at > now


def test_dependency_order_runs_parent_before_child() -> None:
    engine = _new_engine()
    now = datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc)

    engine.schedule_job(
        job_id="parent",
        name="Parent",
        action="embed",
        queue_type=QueueType.EMBEDDING,
        priority=1,
        schedule_type=AutomationScheduleType.ONE_SHOT,
        trigger_type=AutomationTriggerType.SCHEDULED,
        run_at=now - timedelta(seconds=1),
    )
    engine.schedule_job(
        job_id="child",
        name="Child",
        action="recognize",
        queue_type=QueueType.RECOGNITION,
        priority=1,
        schedule_type=AutomationScheduleType.ONE_SHOT,
        trigger_type=AutomationTriggerType.SCHEDULED,
        run_at=now - timedelta(seconds=1),
        dependencies={"parent"},
    )

    runs = engine.run_due(now=now)
    assert [item.job_id for item in runs] == ["parent", "child"]
    assert all(item.status.value == "queued" for item in runs)


def test_retry_and_failure_state_when_enqueue_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _new_engine()
    now = datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc)

    engine.schedule_job(
        job_id="retryable",
        name="Retryable",
        action="boom",
        queue_type=QueueType.SEARCH,
        priority=1,
        schedule_type=AutomationScheduleType.ONE_SHOT,
        trigger_type=AutomationTriggerType.SCHEDULED,
        run_at=now - timedelta(seconds=1),
        retry_policy=AutomationRetryPolicy(max_retries=1, backoff_seconds=1, exponential_backoff=False),
    )

    def _raise(*args, **kwargs):
        raise RuntimeError("enqueue-failed")

    monkeypatch.setattr(engine.queue_manager, "enqueue", _raise)

    first = engine.run_due(now=now)
    assert len(first) == 1
    assert first[0].status.value == "failed"

    snapshot = engine.repository.get_job("retryable")
    assert snapshot is not None
    assert snapshot.state.value == "active"
    assert snapshot.retries == 1

    second = engine.run_due(now=datetime.now(timezone.utc) + timedelta(seconds=2))
    assert len(second) == 1
    assert second[0].status.value == "failed"

    snapshot2 = engine.repository.get_job("retryable")
    assert snapshot2 is not None
    assert snapshot2.state.value == "failed"
    assert snapshot2.retries == 2


def test_pause_resume_cancel_and_progress_reporting() -> None:
    engine = _new_engine()
    now = datetime(2024, 1, 1, 3, 0, tzinfo=timezone.utc)

    engine.schedule_job(
        job_id="j1",
        name="Job One",
        action="search",
        queue_type=QueueType.SEARCH,
        priority=1,
        schedule_type=AutomationScheduleType.ONE_SHOT,
        trigger_type=AutomationTriggerType.SCHEDULED,
        run_at=now,
    )
    engine.schedule_job(
        job_id="j2",
        name="Job Two",
        action="search",
        queue_type=QueueType.SEARCH,
        priority=1,
        schedule_type=AutomationScheduleType.ONE_SHOT,
        trigger_type=AutomationTriggerType.SCHEDULED,
        run_at=now,
    )

    assert engine.pause("j1").success is True
    assert engine.cancel("j2").success is True
    assert engine.resume("j1").success is True

    progress = engine.progress()
    assert progress.total_jobs == 2
    assert progress.active_jobs == 1
    assert progress.cancelled_jobs == 1


def test_manual_event_and_pipeline_triggers() -> None:
    engine = _new_engine()
    now = datetime(2024, 1, 1, 4, 0, tzinfo=timezone.utc)

    engine.schedule_job(
        job_id="manual",
        name="Manual",
        action="search",
        queue_type=QueueType.SEARCH,
        priority=1,
        schedule_type=AutomationScheduleType.ONE_SHOT,
        trigger_type=AutomationTriggerType.MANUAL,
        run_at=now,
    )
    engine.schedule_job(
        job_id="event",
        name="Event",
        action="index",
        queue_type=QueueType.INDEX,
        priority=1,
        schedule_type=AutomationScheduleType.ONE_SHOT,
        trigger_type=AutomationTriggerType.EVENT,
        run_at=now,
        payload={"event_name": "library.updated"},
    )
    engine.schedule_job(
        job_id="pipe",
        name="Pipe",
        action="metadata",
        queue_type=QueueType.METADATA,
        priority=1,
        schedule_type=AutomationScheduleType.ONE_SHOT,
        trigger_type=AutomationTriggerType.PIPELINE,
        run_at=now,
        payload={"queue_type": QueueType.METADATA.value},
    )

    manual = engine.trigger_manual("manual")
    assert manual.status.value == "queued"

    event_runs = engine.trigger_event("library.updated", payload={"kind": "full"})
    assert len(event_runs) == 1
    assert event_runs[0].job_id == "event"

    pipe_runs = engine.trigger_pipeline(QueueType.METADATA, payload={"batch": 1})
    assert len(pipe_runs) == 1
    assert pipe_runs[0].job_id == "pipe"


def test_condition_gating_skips_when_context_not_matching() -> None:
    engine = _new_engine()
    now = datetime(2024, 1, 1, 5, 0, tzinfo=timezone.utc)

    engine.schedule_job(
        job_id="cond",
        name="Conditional",
        action="search",
        queue_type=QueueType.SEARCH,
        priority=1,
        schedule_type=AutomationScheduleType.ONE_SHOT,
        trigger_type=AutomationTriggerType.SCHEDULED,
        run_at=now - timedelta(seconds=1),
        condition=AutomationCondition(key="mode", equals="full"),
    )

    skipped = engine.run_due(now=now, context={"mode": "delta"})
    assert len(skipped) == 1
    assert skipped[0].status.value == "skipped"

    engine.repository.update_job_fields("cond", next_run_at=now - timedelta(seconds=1), state=engine.repository.get_job("cond").state)
    executed = engine.run_due(now=now, context={"mode": "full"})
    assert len(executed) == 1
    assert executed[0].status.value == "queued"


def test_schedule_maintenance_defaults_creates_expected_jobs() -> None:
    engine = _new_engine()
    created = engine.schedule_maintenance_defaults()
    ids = {item.job_id for item in created}

    assert len(created) == 7
    assert "maintenance_scan" in ids
    assert "maintenance_cleanup" in ids
    assert engine.statistics.maintenance_jobs_created == 7


def test_service_dispatch_and_worker_checkpoint_resume() -> None:
    service = AutomationService()

    schedule_job = PipelineJob(
        queue_type=QueueType.SEARCH,
        metadata={
            "stage": "automation",
            "action": "schedule",
            "job_id": "svc-job",
            "name": "Service Job",
            "automation_action": "search",
            "queue_type": QueueType.SEARCH.value,
            "priority": 2,
            "schedule_type": AutomationScheduleType.ONE_SHOT.value,
            "trigger_type": AutomationTriggerType.SCHEDULED.value,
            "run_at": datetime(2024, 1, 1, 6, 0, tzinfo=timezone.utc).isoformat(),
        },
    )
    result = service.process_automation_job(schedule_job)
    assert result is not None
    assert result.success is True

    run_due_job = PipelineJob(
        queue_type=QueueType.SEARCH,
        metadata={
            "stage": "automation",
            "action": "run_due",
            "now": datetime(2024, 1, 1, 6, 1, tzinfo=timezone.utc).isoformat(),
        },
    )

    worker = AutomationWorker(service=service, queue_manager=service.queue_manager)
    results = worker.process_jobs([run_due_job])
    assert len(results) == 1
    assert results[0].action == "run_due"

    # same pipeline job id is checkpointed and skipped on repeated processing
    repeated = worker.process_jobs([run_due_job])
    assert repeated == []

    worker.cancel(str(run_due_job.id))
    assert worker.is_cancelled(str(run_due_job.id)) is True
    worker.resume(str(run_due_job.id))
    assert worker.is_cancelled(str(run_due_job.id)) is False


def test_manual_trigger_unknown_job_raises() -> None:
    engine = _new_engine()
    with pytest.raises(AutomationValidationError):
        engine.trigger_manual("missing-job")
