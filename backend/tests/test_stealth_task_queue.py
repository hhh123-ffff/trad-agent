from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.app import stealth_repository, stealth_tasks


def _task_row(**overrides):
    now = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)
    row = {
        "id": "task-1",
        "status": "running",
        "requested_limit": 12,
        "requested_offset": 5,
        "requested_symbols": ["600000.SH"],
        "requested_include_watchlist": False,
        "active_themes": ["机器人"],
        "worker_id": "worker-a",
        "lease_expires_at": now + timedelta(minutes=20),
        "total": 0,
        "scanned": 0,
        "saved": 0,
        "failed": 0,
        "stages": {},
        "message": "claimed",
        "error": None,
        "created_at": now,
        "started_at": now,
        "finished_at": None,
        "updated_at": now,
    }
    row.update(overrides)
    return row


class _FakeCursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row

    def fetchall(self):
        return [self.row] if self.row else []


class _FakeConn:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append({"sql": sql, "params": params})
        return _FakeCursor(self.row)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_claim_scan_task_uses_worker_lease_and_include_watchlist(monkeypatch):
    conn = _FakeConn(_task_row())
    monkeypatch.setattr(stealth_repository, "connect", lambda: conn)

    task = stealth_repository.claim_scan_task("task-1", worker_id="worker-a", lease_seconds=1200)

    assert task is not None
    assert task.worker_id == "worker-a"
    assert task.requested_include_watchlist is False
    assert task.lease_expires_at is not None
    call = conn.calls[0]
    assert "lease_expires_at" in call["sql"]
    assert call["params"][0] == "worker-a"
    assert call["params"][1] == 1200
    assert call["params"][2] == "task-1"


def test_run_task_from_queue_claims_once_and_uses_persisted_request(monkeypatch):
    claimed = _task_row()
    calls = {}

    monkeypatch.setattr(stealth_tasks, "claim_scan_task", lambda task_id, worker_id: SimpleNamespace(**claimed))
    monkeypatch.setattr(
        stealth_tasks,
        "_run_claimed_task",
        lambda task: calls.setdefault(
            "task",
            {
                "limit": task.requested_limit,
                "offset": task.requested_offset,
                "symbols": task.requested_symbols,
                "active_themes": task.active_themes,
                "include_watchlist": task.requested_include_watchlist,
            },
        ),
    )

    stealth_tasks._run_task_from_queue("task-1", worker_id="worker-a")

    assert calls["task"] == {
        "limit": 12,
        "offset": 5,
        "symbols": ["600000.SH"],
        "active_themes": ["机器人"],
        "include_watchlist": False,
    }


def test_run_task_from_queue_skips_when_already_claimed(monkeypatch):
    monkeypatch.setattr(stealth_tasks, "claim_scan_task", lambda task_id, worker_id: None)

    called = False

    def fail_if_called(task):
        nonlocal called
        called = True

    monkeypatch.setattr(stealth_tasks, "_run_claimed_task", fail_if_called)

    stealth_tasks._run_task_from_queue("task-1", worker_id="worker-b")

    assert called is False
