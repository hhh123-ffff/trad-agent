from datetime import date, datetime, timezone
from types import SimpleNamespace

from backend.app import tracking_service


def test_post_market_replay_job_continues_when_information_source_fails(monkeypatch):
    calls: list[str] = []
    captured_at = datetime(2026, 6, 1, 20, 10, tzinfo=timezone.utc)
    snapshot = SimpleNamespace(
        id="snapshot-1",
        event_ids=[],
        sectors=[],
        captured_at=captured_at,
    )
    report = SimpleNamespace(trading_day=date(2026, 6, 1), sections=[{"title": "data quality"}])

    def fake_snapshot():
        calls.append("snapshot")
        return snapshot

    def fake_news():
        calls.append("news")
        raise RuntimeError("THS token missing")

    def fake_scan(**kwargs):
        calls.append("scan")
        return SimpleNamespace(
            trading_day=date(2026, 6, 1),
            total=0,
            scanned=0,
            saved=0,
            failed=0,
            stages={},
        )

    def fake_journal():
        calls.append("journal")
        return []

    def fake_report(trading_day):
        calls.append("report")
        assert trading_day == date(2026, 6, 1)
        return report

    monkeypatch.setenv("MARKETLENS_POST_MARKET_ENABLE_SCAN", "1")
    monkeypatch.setattr(tracking_service, "capture_market_snapshot", fake_snapshot)
    monkeypatch.setattr(tracking_service, "collect_news_and_announcements", fake_news)
    monkeypatch.setattr(tracking_service, "run_stealth_scan", fake_scan)
    monkeypatch.setattr(tracking_service, "snapshot_observation_journal", fake_journal)
    monkeypatch.setattr(tracking_service, "build_daily_tracking_report", fake_report)

    scope, message = tracking_service._post_market_replay_job()

    assert calls == ["snapshot", "news", "scan", "journal", "report"]
    assert scope["information"]["status"] == "failed"
    assert scope["information"]["error"] == "THS token missing"
    assert scope["news"] == 0
    assert scope["announcements"] == 0
    assert scope["report_sections"] == 1
    assert "部分完成" in message


def test_tracking_job_lock_uses_local_mutex_when_redis_unavailable(monkeypatch):
    class BrokenRedis:
        def set(self, *args, **kwargs):
            raise RuntimeError("redis unavailable")

        def get(self, key):
            raise RuntimeError("redis unavailable")

        def delete(self, key):
            raise RuntimeError("redis unavailable")

    monkeypatch.setattr(tracking_service, "get_redis", lambda: BrokenRedis())
    lock_key = "guanlan:test-lock:redis-down"

    first = tracking_service._acquire_lock(lock_key)
    second = tracking_service._acquire_lock(lock_key)

    try:
        assert first is not None
        assert first.startswith("local:")
        assert second is None
    finally:
        if first:
            tracking_service._release_lock(lock_key, first)

    third = tracking_service._acquire_lock(lock_key)
    try:
        assert third is not None
        assert third.startswith("local:")
    finally:
        if third:
            tracking_service._release_lock(lock_key, third)


def test_post_market_replay_job_runs_bounded_close_loop(monkeypatch):
    calls: list[str] = []
    captured_at = datetime(2026, 6, 1, 20, 10, tzinfo=timezone.utc)
    snapshot = SimpleNamespace(
        id="snapshot-1",
        event_ids=["event-1", "event-2"],
        sectors=[SimpleNamespace(name="半导体"), SimpleNamespace(name="机器人")],
        captured_at=captured_at,
    )
    report = SimpleNamespace(trading_day=date(2026, 6, 1), sections=[{"title": "市场温度"}])

    def fake_snapshot():
        calls.append("snapshot")
        return snapshot

    def fake_news():
        calls.append("news")
        return [object()], [object(), object()]

    def fake_scan(**kwargs):
        calls.append("scan")
        assert kwargs["limit"] == 12
        assert kwargs["offset"] == 5
        assert kwargs["active_themes"] == ["半导体", "机器人"]
        assert kwargs["include_watchlist"] is True
        return SimpleNamespace(
            trading_day=date(2026, 6, 1),
            total=12,
            scanned=12,
            saved=3,
            failed=0,
            stages={"潜伏观察": 2, "启动确认": 1},
        )

    def fake_journal():
        calls.append("journal")
        return [object()]

    def fake_report(trading_day):
        calls.append("report")
        assert trading_day == date(2026, 6, 1)
        return report

    monkeypatch.setenv("MARKETLENS_POST_MARKET_ENABLE_SCAN", "1")
    monkeypatch.setenv("MARKETLENS_POST_MARKET_SCAN_LIMIT", "12")
    monkeypatch.setenv("MARKETLENS_POST_MARKET_SCAN_OFFSET", "5")
    monkeypatch.setattr(tracking_service, "capture_market_snapshot", fake_snapshot)
    monkeypatch.setattr(tracking_service, "collect_news_and_announcements", fake_news)
    monkeypatch.setattr(tracking_service, "run_stealth_scan", fake_scan)
    monkeypatch.setattr(tracking_service, "snapshot_observation_journal", fake_journal)
    monkeypatch.setattr(tracking_service, "build_daily_tracking_report", fake_report)

    scope, message = tracking_service._post_market_replay_job()

    assert calls == ["snapshot", "news", "scan", "journal", "report"]
    assert scope["snapshot_id"] == "snapshot-1"
    assert scope["news"] == 1
    assert scope["announcements"] == 2
    assert scope["observation_journal"] == 1
    assert scope["scan"]["saved"] == 3
    assert "盘后一键复盘已完成" in message


def test_post_market_replay_job_continues_when_snapshot_fails(monkeypatch):
    calls: list[str] = []
    report = SimpleNamespace(trading_day=date(2026, 6, 1), sections=[{"title": "数据质量与缺口"}])

    def fake_snapshot():
        calls.append("snapshot")
        raise RuntimeError("行情源不可用")

    def fake_news():
        calls.append("news")
        return [], []

    def fake_scan(**kwargs):
        calls.append("scan")
        assert kwargs["active_themes"] == []
        return SimpleNamespace(
            trading_day=date(2026, 6, 1),
            total=0,
            scanned=0,
            saved=0,
            failed=0,
            stages={},
        )

    def fake_journal():
        calls.append("journal")
        return []

    def fake_report(trading_day):
        calls.append("report")
        return report

    monkeypatch.setenv("MARKETLENS_POST_MARKET_ENABLE_SCAN", "1")
    monkeypatch.setenv("MARKETLENS_POST_MARKET_SCAN_LIMIT", "1")
    monkeypatch.setattr(tracking_service, "capture_market_snapshot", fake_snapshot)
    monkeypatch.setattr(tracking_service, "collect_news_and_announcements", fake_news)
    monkeypatch.setattr(tracking_service, "run_stealth_scan", fake_scan)
    monkeypatch.setattr(tracking_service, "snapshot_observation_journal", fake_journal)
    monkeypatch.setattr(tracking_service, "build_daily_tracking_report", fake_report)

    scope, message = tracking_service._post_market_replay_job()

    assert calls == ["snapshot", "news", "scan", "journal", "report"]
    assert scope["snapshot"]["status"] == "failed"
    assert scope["events"] == 0
    assert "部分完成" in message
