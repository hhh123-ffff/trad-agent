from datetime import datetime

from backend.app import tracking_service
from backend.app.data_freshness import DataFreshnessInputs
from backend.app.database import connect, init_schema


def _delete_run(run_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM job_runs WHERE id = %s", (run_id,))


def test_scheduled_replay_records_skipped_run_on_weekend(monkeypatch):
    init_schema()
    called = False

    def manual_run(_):
        nonlocal called
        called = True

    monkeypatch.setattr(tracking_service, "run_tracking_job", manual_run)
    run = tracking_service.run_scheduled_tracking_job("post_market_replay", now=datetime(2026, 6, 6, 20, 10))

    try:
        assert run.status == "skipped"
        assert run.affected_scope["skip_reason"] == "non_trading_day"
        assert called is False
    finally:
        _delete_run(run.id)


def test_scheduled_replay_runs_when_current_market_date_is_confirmed(monkeypatch):
    target = datetime(2026, 6, 5, 20, 10)
    expected = object()
    monkeypatch.setattr(
        tracking_service,
        "load_data_freshness_inputs",
        lambda: DataFreshnessInputs(snapshot_date=target.date()),
    )
    monkeypatch.setattr(tracking_service, "run_tracking_job", lambda job_name: expected if job_name == "post_market_replay" else None)

    assert tracking_service.run_scheduled_tracking_job("post_market_replay", now=target) is expected


def test_scheduled_replay_skips_unconfirmed_weekday(monkeypatch):
    init_schema()
    target = datetime(2026, 6, 5, 20, 10)
    monkeypatch.setattr(tracking_service, "load_data_freshness_inputs", lambda: DataFreshnessInputs())
    monkeypatch.setattr(tracking_service, "run_tracking_job", lambda _: (_ for _ in ()).throw(AssertionError("manual run should not start")))

    run = tracking_service.run_scheduled_tracking_job("post_market_replay", now=target)
    try:
        assert run.status == "skipped"
        assert run.affected_scope["skip_reason"] == "trading_day_unconfirmed"
    finally:
        _delete_run(run.id)
