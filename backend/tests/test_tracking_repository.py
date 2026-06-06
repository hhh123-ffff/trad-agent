from uuid import uuid4

from backend.app.database import connect, init_schema
from backend.app.tracking_repository import (
    create_app_notification,
    create_job_run,
    create_job_run_step,
    finish_job_run,
    finish_job_run_step,
    get_job_run_detail,
    list_app_notifications,
    list_job_run_steps,
    mark_app_notification_read,
)


def _delete_job_run(run_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM app_notifications WHERE related_job_run_id = %s", (run_id,))
        conn.execute("DELETE FROM job_run_steps WHERE job_run_id = %s", (run_id,))
        conn.execute("DELETE FROM job_runs WHERE id = %s", (run_id,))


def test_job_run_detail_preserves_independent_step_attempts():
    init_schema()
    run = create_job_run(f"repository-test-{uuid4().hex}")

    try:
        first = create_job_run_step(run.id, "collect_information", attempt=1)
        finish_job_run_step(
            first.id,
            status="failed",
            result_scope={"provider": "ths"},
            error_code="missing_credentials",
            error="THS token missing",
            retryable=False,
        )
        second = create_job_run_step(run.id, "collect_information", attempt=2)
        finish_job_run_step(
            second.id,
            status="completed",
            result_scope={"news": 2, "announcements": 3},
        )
        finish_job_run(run.id, "degraded", affected_scope={"data_freshness": {"status": "stale"}})

        steps = list_job_run_steps(run.id)
        detail = get_job_run_detail(run.id)

        assert [step.attempt for step in steps] == [1, 2]
        assert steps[0].status == "failed"
        assert steps[0].error_code == "missing_credentials"
        assert steps[0].retryable is False
        assert steps[1].status == "completed"
        assert steps[1].result_scope == {"news": 2, "announcements": 3}
        assert detail is not None
        assert detail.run.status == "degraded"
        assert detail.run.affected_scope["data_freshness"]["status"] == "stale"
        assert [step.id for step in detail.steps] == [first.id, second.id]
    finally:
        _delete_job_run(run.id)


def test_app_notification_can_be_listed_and_marked_read():
    init_schema()
    run = create_job_run(f"notification-test-{uuid4().hex}")

    try:
        notification = create_app_notification(
            notification_type="pipeline_degraded",
            severity="warning",
            title="Daily loop degraded",
            message="Information source is unavailable.",
            related_job_run_id=run.id,
            metadata={"affected_steps": ["collect_information"]},
        )

        unread = list_app_notifications(unread_only=True, limit=10)
        assert any(item.id == notification.id for item in unread)
        assert notification.read_at is None
        assert notification.metadata == {"affected_steps": ["collect_information"]}

        updated = mark_app_notification_read(notification.id)
        assert updated is not None
        assert updated.read_at is not None
        assert all(item.id != notification.id for item in list_app_notifications(unread_only=True, limit=100))
    finally:
        _delete_job_run(run.id)
