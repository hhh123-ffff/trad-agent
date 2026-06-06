from uuid import uuid4

from backend.app.database import connect, init_schema
from backend.app.job_pipeline import (
    ConfigurationStepError,
    MissingCredentialsStepError,
    StepOutcome,
    aggregate_pipeline_status,
    run_pipeline_step,
)
from backend.app.tracking_repository import create_job_run, list_job_run_steps


def _delete_job_run(run_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM job_run_steps WHERE job_run_id = %s", (run_id,))
        conn.execute("DELETE FROM job_runs WHERE id = %s", (run_id,))


def test_pipeline_step_retries_temporary_failure_and_preserves_attempts():
    init_schema()
    run = create_job_run(f"pipeline-test-{uuid4().hex}")
    calls = 0

    def handler() -> StepOutcome:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TimeoutError("provider timed out")
        return StepOutcome(result_scope={"snapshots": 1})

    try:
        result = run_pipeline_step(run.id, "close_snapshot", handler, sleep=lambda _: None)
        attempts = list_job_run_steps(run.id)

        assert result.status == "completed"
        assert result.result_scope == {"snapshots": 1}
        assert calls == 3
        assert [item.status for item in attempts] == ["failed", "failed", "completed"]
        assert [item.attempt for item in attempts] == [1, 2, 3]
        assert attempts[0].error_code == "temporary_provider_error"
        assert attempts[0].retryable is True
    finally:
        _delete_job_run(run.id)


def test_pipeline_step_does_not_retry_missing_credentials_or_configuration():
    init_schema()
    run = create_job_run(f"pipeline-test-{uuid4().hex}")

    try:
        missing = run_pipeline_step(
            run.id,
            "collect_information",
            lambda: (_ for _ in ()).throw(MissingCredentialsStepError("THS token missing")),
            sleep=lambda _: None,
        )
        invalid = run_pipeline_step(
            run.id,
            "stealth_scan",
            lambda: (_ for _ in ()).throw(ConfigurationStepError("scan limit is invalid")),
            sleep=lambda _: None,
        )
        attempts = list_job_run_steps(run.id)

        assert missing.status == "failed"
        assert missing.error_code == "missing_credentials"
        assert invalid.status == "failed"
        assert invalid.error_code == "configuration_error"
        assert [item.attempt for item in attempts] == [1, 1]
        assert all(item.retryable is False for item in attempts)
    finally:
        _delete_job_run(run.id)


def test_pipeline_status_aggregation_respects_degraded_steps_and_daily_report():
    init_schema()
    run = create_job_run(f"pipeline-test-{uuid4().hex}")

    try:
        run_pipeline_step(run.id, "close_snapshot", lambda: StepOutcome())
        run_pipeline_step(
            run.id,
            "collect_information",
            lambda: StepOutcome(status="degraded", result_scope={"warnings": ["source unavailable"]}),
        )
        run_pipeline_step(run.id, "daily_report", lambda: StepOutcome(result_scope={"report": "ready"}))
        steps = list_job_run_steps(run.id)
        assert aggregate_pipeline_status(steps) == "degraded"

        failed_run = create_job_run(f"pipeline-test-{uuid4().hex}")
        try:
            run_pipeline_step(
                failed_run.id,
                "daily_report",
                lambda: (_ for _ in ()).throw(RuntimeError("report storage failed")),
            )
            assert aggregate_pipeline_status(list_job_run_steps(failed_run.id)) == "failed"
        finally:
            _delete_job_run(failed_run.id)
    finally:
        _delete_job_run(run.id)
