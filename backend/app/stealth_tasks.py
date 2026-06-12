from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import socket
from threading import Lock
from uuid import uuid4

from .models import StealthScanRunRequest, StealthScanTask
from .stealth_repository import (
    claim_scan_task,
    create_scan_task,
    get_scan_task,
    increment_scan_failure_retry_count,
    list_queued_scan_tasks,
    list_scan_failures,
    mark_symbol_scan_failures_resolved,
    record_scan_failure,
    snapshot_observation_journal,
    update_scan_task,
)
from .stealth_scanner import run_stealth_scan


_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stealth-scan")
_submit_lock = Lock()
_WORKER_ID = f"{socket.gethostname()}:{uuid4().hex[:10]}"


def enqueue_stealth_scan_task(request: StealthScanRunRequest, active_themes: list[str], include_watchlist: bool = True) -> StealthScanTask:
    symbols = [symbol.upper() for symbol in request.symbols]
    task = create_scan_task(
        requested_limit=request.limit,
        requested_offset=request.offset,
        requested_symbols=symbols,
        active_themes=active_themes,
        requested_include_watchlist=include_watchlist,
    )
    with _submit_lock:
        _executor.submit(_run_task_from_queue, task.id, _WORKER_ID)
    return task


def enqueue_failed_symbols_retry(task_id: str, active_themes: list[str]) -> StealthScanTask | None:
    failures = list_scan_failures(task_id, unresolved_only=True)
    symbols = sorted({failure.symbol for failure in failures})
    if not symbols:
        return None
    increment_scan_failure_retry_count(task_id, symbols)
    request = StealthScanRunRequest(symbols=symbols)
    return enqueue_stealth_scan_task(request, active_themes, include_watchlist=False)


def resume_queued_stealth_scan_tasks(limit: int = 5) -> int:
    queued = list_queued_scan_tasks(limit=limit)
    with _submit_lock:
        for task in queued:
            _executor.submit(_run_task_from_queue, task.id, _WORKER_ID)
    return len(queued)


def _run_task_from_queue(task_id: str, worker_id: str = _WORKER_ID) -> None:
    task = claim_scan_task(task_id, worker_id=worker_id)
    if task is None:
        return
    _run_claimed_task(task)


def _run_claimed_task(task: StealthScanTask) -> None:
    task_id = task.id
    update_scan_task(
        task_id,
        status="running",
        started=True,
        message="后台扫描已启动，正在拉取全 A 股票池与历史数据。",
    )

    def progress(payload: dict[str, object]) -> None:
        update_scan_task(
            task_id,
            total=_int_or_none(payload.get("total")),
            scanned=_int_or_none(payload.get("scanned")),
            saved=_int_or_none(payload.get("saved")),
            failed=_int_or_none(payload.get("failed")),
            stages=_dict_or_none(payload.get("stages")),
            message=str(payload.get("message") or "后台扫描进行中。"),
        )

    def failure(payload: dict[str, object]) -> None:
        record_scan_failure(
            task_id=task_id,
            symbol=str(payload.get("symbol") or ""),
            name=str(payload.get("name") or ""),
            stage=str(payload.get("stage") or "history"),
            error=str(payload.get("error") or "历史数据不可用"),
        )

    def success(symbol: str) -> None:
        mark_symbol_scan_failures_resolved(symbol)

    try:
        result = run_stealth_scan(
            limit=task.requested_limit,
            offset=task.requested_offset,
            symbols=task.requested_symbols,
            active_themes=task.active_themes,
            progress=progress,
            failure=failure,
            success=success,
            include_watchlist=task.requested_include_watchlist,
        )
        journal_message = ""
        try:
            snapshot_symbols = task.requested_symbols if task.requested_symbols else None
            journal_entries = snapshot_observation_journal(symbols=snapshot_symbols)
            if journal_entries:
                journal_message = f" 已记录观察日志 {len(journal_entries)} 条。"
        except Exception as exc:
            journal_message = f" 观察日志暂未记录：{exc}"
        update_scan_task(
            task_id,
            status="completed",
            total=result.total,
            scanned=result.scanned,
            saved=result.saved,
            failed=result.failed,
            stages=result.stages,
            message=f"{result.message}{journal_message}",
            finished=True,
        )
    except Exception as exc:
        update_scan_task(
            task_id,
            status="failed",
            error=str(exc),
            message="后台扫描失败，已保存失败原因，可稍后重试。",
            finished=True,
        )


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dict_or_none(value: object) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, int] = {}
    for key, raw in value.items():
        try:
            result[str(key)] = int(raw)
        except (TypeError, ValueError):
            continue
    return result


def reload_scan_task(task_id: str) -> StealthScanTask | None:
    return get_scan_task(task_id)
