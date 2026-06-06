from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from backend.app import tracking_service
from backend.app.data_freshness import DataFreshnessInputs, DataFreshnessResult, FreshnessCheck
from backend.app.database import connect, init_schema
from backend.app.tracking_repository import list_app_notifications, list_job_run_steps


TRADING_DAY = date(2026, 6, 1)


def _delete_run(run_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM app_notifications WHERE related_job_run_id = %s", (run_id,))
        conn.execute("DELETE FROM job_run_steps WHERE job_run_id = %s", (run_id,))
        conn.execute("DELETE FROM job_runs WHERE id = %s", (run_id,))


def _fresh_result(status: str = "fresh") -> DataFreshnessResult:
    check = FreshnessCheck(
        scope="market_snapshot",
        status=status,
        expected_date=TRADING_DAY,
        actual_date=TRADING_DAY if status == "fresh" else date(2026, 5, 29),
        message="freshness test",
    )
    return DataFreshnessResult(status=status, checks=[check])


@pytest.fixture(autouse=True)
def replay_dependencies(monkeypatch):
    init_schema()
    monkeypatch.setenv("MARKETLENS_POST_MARKET_ENABLE_SCAN", "1")
    monkeypatch.setattr(tracking_service, "_acquire_lock", lambda _: "test-lock")
    monkeypatch.setattr(tracking_service, "_release_lock", lambda *_: None)
    monkeypatch.setattr(tracking_service, "load_data_freshness_inputs", lambda: DataFreshnessInputs())
    monkeypatch.setattr(tracking_service, "evaluate_data_freshness", lambda *_: _fresh_result())


def _install_successful_steps(monkeypatch, calls: list[str]) -> None:
    snapshot = SimpleNamespace(
        id="snapshot-1",
        event_ids=["event-1"],
        sectors=[SimpleNamespace(name="semiconductor")],
        captured_at=datetime(2026, 6, 1, 15, 5, tzinfo=timezone.utc),
    )
    report = SimpleNamespace(trading_day=TRADING_DAY, sections=[{"title": "data quality"}])

    monkeypatch.setattr(tracking_service, "capture_market_snapshot", lambda: calls.append("close_snapshot") or snapshot)
    monkeypatch.setattr(
        tracking_service,
        "collect_news_and_announcements",
        lambda: calls.append("collect_information") or ([object()], [object()]),
    )
    monkeypatch.setattr(
        tracking_service,
        "run_stealth_scan",
        lambda **_: calls.append("stealth_scan")
        or SimpleNamespace(trading_day=TRADING_DAY, total=1, scanned=1, saved=1, failed=0, stages={"watch": 1}),
    )
    monkeypatch.setattr(tracking_service, "snapshot_observation_journal", lambda: calls.append("observation_journal") or [object()])
    monkeypatch.setattr(tracking_service, "build_daily_tracking_report", lambda _: calls.append("daily_report") or report)
    monkeypatch.setattr(
        tracking_service,
        "_agent_post_market_job",
        lambda: calls.append("agent_post_market") or ({"agent_status": "completed", "agent_run_id": "agent-1"}, "agent complete"),
    )


def test_post_market_replay_persists_six_completed_steps(monkeypatch):
    calls: list[str] = []
    _install_successful_steps(monkeypatch, calls)

    run = tracking_service.run_tracking_job("post_market_replay")
    try:
        steps = list_job_run_steps(run.id)
        assert run.status == "completed"
        assert calls == [
            "close_snapshot",
            "collect_information",
            "stealth_scan",
            "observation_journal",
            "daily_report",
            "agent_post_market",
        ]
        assert [step.step_name for step in steps] == calls
        assert all(step.status == "completed" for step in steps)
        assert run.affected_scope["data_freshness"]["status"] == "fresh"
        assert any(item.notification_type == "pipeline_completed" for item in list_app_notifications(limit=20) if item.related_job_run_id == run.id)
    finally:
        _delete_run(run.id)


def test_post_market_replay_degrades_missing_credentials_and_continues(monkeypatch):
    calls: list[str] = []
    _install_successful_steps(monkeypatch, calls)

    def missing_information():
        calls.append("collect_information")
        raise RuntimeError("THS token missing")

    monkeypatch.setattr(tracking_service, "collect_news_and_announcements", missing_information)

    run = tracking_service.run_tracking_job("post_market_replay")
    try:
        steps = list_job_run_steps(run.id)
        information = next(step for step in steps if step.step_name == "collect_information")
        assert run.status == "degraded"
        assert information.status == "failed"
        assert information.error_code == "missing_credentials"
        assert information.attempt == 1
        assert "daily_report" in calls
        assert "agent_post_market" in calls
        assert any(item.notification_type == "pipeline_degraded" for item in list_app_notifications(limit=20) if item.related_job_run_id == run.id)
    finally:
        _delete_run(run.id)


def test_post_market_replay_fails_when_daily_report_fails(monkeypatch):
    calls: list[str] = []
    _install_successful_steps(monkeypatch, calls)

    def failed_report(_):
        calls.append("daily_report")
        raise RuntimeError("report generation failed")

    monkeypatch.setattr(tracking_service, "build_daily_tracking_report", failed_report)

    run = tracking_service.run_tracking_job("post_market_replay")
    try:
        steps = list_job_run_steps(run.id)
        report = next(step for step in steps if step.step_name == "daily_report")
        agent = next(step for step in steps if step.step_name == "agent_post_market")
        assert run.status == "failed"
        assert report.status == "failed"
        assert agent.status == "skipped"
        assert "agent_post_market" not in calls
        assert any(item.notification_type == "pipeline_failed" for item in list_app_notifications(limit=20) if item.related_job_run_id == run.id)
    finally:
        _delete_run(run.id)


def test_post_market_replay_degrades_and_notifies_when_data_is_stale(monkeypatch):
    calls: list[str] = []
    _install_successful_steps(monkeypatch, calls)
    monkeypatch.setattr(tracking_service, "evaluate_data_freshness", lambda *_: _fresh_result("stale"))

    run = tracking_service.run_tracking_job("post_market_replay")
    try:
        notification_types = {
            item.notification_type
            for item in list_app_notifications(limit=20)
            if item.related_job_run_id == run.id
        }
        assert run.status == "degraded"
        assert run.affected_scope["data_freshness"]["status"] == "stale"
        assert notification_types == {"pipeline_degraded", "data_stale"}
    finally:
        _delete_run(run.id)


def test_post_market_replay_uses_successful_steps_as_freshness_coverage(monkeypatch):
    calls: list[str] = []
    _install_successful_steps(monkeypatch, calls)
    captured_inputs: list[DataFreshnessInputs] = []
    monkeypatch.setattr(tracking_service, "collect_news_and_announcements", lambda: calls.append("collect_information") or ([], []))

    def capture_freshness(_, inputs):
        captured_inputs.append(inputs)
        return _fresh_result()

    monkeypatch.setattr(tracking_service, "evaluate_data_freshness", capture_freshness)

    run = tracking_service.run_tracking_job("post_market_replay")
    try:
        assert captured_inputs
        inputs = captured_inputs[0]
        assert inputs.snapshot_date == TRADING_DAY
        assert inputs.announcement_coverage_date == TRADING_DAY
        assert inputs.report_date == TRADING_DAY
        assert inputs.agent_report_date == TRADING_DAY
    finally:
        _delete_run(run.id)
