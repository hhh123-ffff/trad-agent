from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from .database import connect
from .data_providers import history_provider_sources
from .market_scope import is_mainboard_symbol, is_st_or_delisting_name, mainboard_symbol_sql
from .models import (
    DailyBar,
    ObservationItem,
    ObservationJournalEntry,
    ObservationSummary,
    ObservationSummaryBucket,
    StealthDataQualitySummary,
    StealthCandidate,
    StealthScanAlert,
    StealthScanFailure,
    StealthScanMonitor,
    StealthScanTask,
    ThemeMembership,
    StockUniverseItem,
)
from .repositories import DEFAULT_USER_ID


def _json(value: Any) -> Jsonb:
    return Jsonb(value)


def ensure_stealth_source() -> None:
    with connect() as conn:
        for source in history_provider_sources():
            conn.execute(
                """
                INSERT INTO data_sources (id, name, url, as_of, license, freshness)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    url = EXCLUDED.url,
                    as_of = EXCLUDED.as_of,
                    license = EXCLUDED.license,
                    freshness = EXCLUDED.freshness,
                    updated_at = NOW()
                """,
                (source.id, source.name, source.url, source.as_of, source.license, source.freshness),
            )


def save_universe_items(items: list[StockUniverseItem]) -> None:
    if not items:
        return
    ensure_stealth_source()
    with connect() as conn:
        for item in items:
            conn.execute(
                """
                INSERT INTO stock_universe (symbol, name, is_st, listed_days, market)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (symbol) DO UPDATE SET
                    name = EXCLUDED.name,
                    is_st = EXCLUDED.is_st,
                    listed_days = EXCLUDED.listed_days,
                    market = EXCLUDED.market,
                    updated_at = NOW()
                """,
                (item.symbol, item.name, item.is_st, item.listed_days, item.market),
            )


def save_daily_bars(bars: list[DailyBar]) -> None:
    if not bars:
        return
    with connect() as conn:
        for bar in bars:
            conn.execute(
                """
                INSERT INTO daily_bars (
                    symbol, trade_date, open, high, low, close, volume, amount,
                    change_pct, turnover_rate, adjust
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, trade_date, adjust) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    amount = EXCLUDED.amount,
                    change_pct = EXCLUDED.change_pct,
                    turnover_rate = EXCLUDED.turnover_rate,
                    updated_at = NOW()
                """,
                (
                    bar.symbol,
                    bar.trade_date,
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                    bar.amount,
                    bar.change_pct,
                    bar.turnover_rate,
                    bar.adjust,
                ),
            )


def save_theme_memberships(memberships: list[ThemeMembership]) -> None:
    if not memberships:
        return
    with connect() as conn:
        for item in memberships:
            conn.execute(
                """
                INSERT INTO theme_memberships (symbol, theme_name, theme_type)
                VALUES (%s, %s, %s)
                ON CONFLICT (symbol, theme_name, theme_type) DO UPDATE SET updated_at = NOW()
                """,
                (item.symbol, item.theme_name, item.theme_type),
            )


def save_scan_results(candidates: list[StealthCandidate]) -> None:
    candidates = [
        candidate
        for candidate in candidates
        if is_mainboard_symbol(candidate.symbol) and not is_st_or_delisting_name(candidate.name)
    ]
    if not candidates:
        return
    ensure_stealth_source()
    with connect() as conn:
        for candidate in candidates:
            conn.execute(
                """
                INSERT INTO stealth_scan_results (
                    trading_day, symbol, name, stage, total_score, accumulation_score,
                    launch_score, theme_score, risk_penalty, evidence, risks, metrics, source_ids
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (trading_day, symbol) DO UPDATE SET
                    name = EXCLUDED.name,
                    stage = EXCLUDED.stage,
                    total_score = EXCLUDED.total_score,
                    accumulation_score = EXCLUDED.accumulation_score,
                    launch_score = EXCLUDED.launch_score,
                    theme_score = EXCLUDED.theme_score,
                    risk_penalty = EXCLUDED.risk_penalty,
                    evidence = EXCLUDED.evidence,
                    risks = EXCLUDED.risks,
                    metrics = EXCLUDED.metrics,
                    source_ids = EXCLUDED.source_ids,
                    updated_at = NOW()
                """,
                (
                    candidate.trading_day,
                    candidate.symbol,
                    candidate.name,
                    candidate.stage,
                    candidate.total_score,
                    candidate.accumulation_score,
                    candidate.launch_score,
                    candidate.theme_score,
                    candidate.risk_penalty,
                    _json(candidate.evidence),
                    _json(candidate.risks),
                    _json(candidate.metrics),
                    _json(candidate.source_ids),
                ),
            )


def create_scan_task(
    requested_limit: int | None,
    requested_offset: int,
    requested_symbols: list[str],
    active_themes: list[str],
) -> StealthScanTask:
    task_id = uuid4().hex
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO stealth_scan_tasks (
                id, status, requested_limit, requested_offset, requested_symbols, active_themes, message
            )
            VALUES (%s, 'queued', %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                task_id,
                requested_limit,
                requested_offset,
                _json(requested_symbols),
                _json(active_themes),
                "扫描任务已排队，等待后台执行。",
            ),
        ).fetchone()
    return _scan_task_from_row(row)


def update_scan_task(
    task_id: str,
    *,
    status: str | None = None,
    total: int | None = None,
    scanned: int | None = None,
    saved: int | None = None,
    failed: int | None = None,
    stages: dict[str, int] | None = None,
    message: str | None = None,
    error: str | None = None,
    started: bool = False,
    finished: bool = False,
) -> StealthScanTask | None:
    assignments = ["updated_at = NOW()"]
    values: list[Any] = []
    if status is not None:
        assignments.append("status = %s")
        values.append(status)
    if total is not None:
        assignments.append("total = %s")
        values.append(total)
    if scanned is not None:
        assignments.append("scanned = %s")
        values.append(scanned)
    if saved is not None:
        assignments.append("saved = %s")
        values.append(saved)
    if failed is not None:
        assignments.append("failed = %s")
        values.append(failed)
    if stages is not None:
        assignments.append("stages = %s")
        values.append(_json(stages))
    if message is not None:
        assignments.append("message = %s")
        values.append(message)
    if error is not None:
        assignments.append("error = %s")
        values.append(error)
    if started:
        assignments.append("started_at = COALESCE(started_at, NOW())")
    if finished:
        assignments.append("finished_at = NOW()")
    values.append(task_id)
    with connect() as conn:
        row = conn.execute(
            f"""
            UPDATE stealth_scan_tasks
            SET {", ".join(assignments)}
            WHERE id = %s
            RETURNING *
            """,
            tuple(values),
        ).fetchone()
    return _scan_task_from_row(row) if row else None


def record_scan_failure(task_id: str, symbol: str, name: str, stage: str, error: str) -> StealthScanFailure:
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO stealth_scan_failures (task_id, symbol, name, stage, error)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (task_id, symbol, stage) DO UPDATE SET
                name = EXCLUDED.name,
                error = EXCLUDED.error,
                resolved = FALSE,
                updated_at = NOW()
            RETURNING *
            """,
            (task_id, symbol, name, stage, error[:3000]),
        ).fetchone()
    return _scan_failure_from_row(row)


def list_scan_failures(task_id: str, unresolved_only: bool = False) -> list[StealthScanFailure]:
    where = "task_id = %s"
    values: list[Any] = [task_id]
    if unresolved_only:
        where += " AND resolved = FALSE"
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM stealth_scan_failures
            WHERE {where}
            ORDER BY resolved ASC, created_at DESC, id DESC
            """,
            tuple(values),
        ).fetchall()
    return [_scan_failure_from_row(row) for row in rows]


def increment_scan_failure_retry_count(task_id: str, symbols: list[str]) -> None:
    if not symbols:
        return
    with connect() as conn:
        conn.execute(
            """
            UPDATE stealth_scan_failures
            SET retry_count = retry_count + 1,
                updated_at = NOW()
            WHERE task_id = %s
              AND symbol = ANY(%s)
              AND resolved = FALSE
            """,
            (task_id, symbols),
        )


def mark_symbol_scan_failures_resolved(symbol: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE stealth_scan_failures
            SET resolved = TRUE,
                updated_at = NOW()
            WHERE symbol = %s
              AND resolved = FALSE
            """,
            (symbol,),
        )


def mark_task_scan_failures_resolved(task_id: str) -> int:
    with connect() as conn:
        cursor = conn.execute(
            """
            UPDATE stealth_scan_failures
            SET resolved = TRUE,
                updated_at = NOW()
            WHERE task_id = %s
              AND resolved = FALSE
            """,
            (task_id,),
        )
    return int(cursor.rowcount or 0)


def get_scan_task(task_id: str) -> StealthScanTask | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM stealth_scan_tasks WHERE id = %s", (task_id,)).fetchone()
    return _scan_task_from_row(row) if row else None


def latest_scan_task() -> StealthScanTask | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM stealth_scan_tasks ORDER BY created_at DESC LIMIT 1").fetchone()
    return _scan_task_from_row(row) if row else None


def list_recent_scan_tasks(limit: int = 6) -> list[StealthScanTask]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM stealth_scan_tasks
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return [_scan_task_from_row(row) for row in rows]


def build_scan_monitor() -> StealthScanMonitor:
    latest_tasks = list_recent_scan_tasks()
    running_task = next((task for task in latest_tasks if task.status in {"queued", "running"}), None)
    with connect() as conn:
        avg_row = conn.execute(
            """
            SELECT AVG(EXTRACT(EPOCH FROM (finished_at - started_at))) AS avg_seconds
            FROM stealth_scan_tasks
            WHERE status = 'completed'
              AND started_at IS NOT NULL
              AND finished_at IS NOT NULL
              AND created_at >= NOW() - INTERVAL '7 days'
            """
        ).fetchone()
        unresolved_row = conn.execute("SELECT COUNT(*) AS count FROM stealth_scan_failures WHERE resolved = FALSE").fetchone()
    data_quality = build_data_quality_summary()
    latest_completed = next((task for task in latest_tasks if task.status == "completed" and task.total > 0), None)
    latest_failure_rate = (latest_completed.failed / latest_completed.total) if latest_completed else 0
    avg_duration_seconds = round(float(avg_row["avg_seconds"] or 0), 2) if avg_row else 0
    unresolved_failures = int(unresolved_row["count"] or 0) if unresolved_row else 0
    alerts = _scan_alerts(
        latest_tasks=latest_tasks,
        running_task=running_task,
        latest_failure_rate=latest_failure_rate,
        unresolved_failures=unresolved_failures,
        data_quality=data_quality,
    )
    return StealthScanMonitor(
        latest_tasks=latest_tasks,
        running_task=running_task,
        avg_duration_seconds=avg_duration_seconds,
        latest_failure_rate=round(latest_failure_rate, 4),
        unresolved_failures=unresolved_failures,
        data_quality=data_quality,
        alerts=alerts,
    )


def build_data_quality_summary() -> StealthDataQualitySummary:
    eligible_daily_bars = (
        f"{mainboard_symbol_sql('d.symbol')} "
        "AND u.symbol IS NOT NULL "
        "AND COALESCE(u.is_st, FALSE) = FALSE "
        "AND UPPER(COALESCE(u.name, d.symbol)) NOT LIKE '%%ST%%' "
        "AND COALESCE(u.name, d.symbol) NOT LIKE '%%退%%'"
    )
    with connect() as conn:
        latest_row = conn.execute(
            f"""
            SELECT d.trade_date AS latest_trade_date
            FROM daily_bars d
            LEFT JOIN stock_universe u ON u.symbol = d.symbol
            WHERE d.adjust = 'qfq' AND {eligible_daily_bars}
            GROUP BY d.trade_date
            ORDER BY COUNT(DISTINCT d.symbol) DESC, d.trade_date DESC
            LIMIT 1
            """
        ).fetchone()
        latest_day = latest_row["latest_trade_date"] if latest_row else None
        universe_row = conn.execute(
            f"SELECT COUNT(*) AS count FROM stock_universe WHERE is_st = FALSE AND {mainboard_symbol_sql('symbol')} AND UPPER(name) NOT LIKE '%%ST%%' AND name NOT LIKE '%%退%%'"
        ).fetchone()
        symbols_row = conn.execute(
            f"""
            SELECT COUNT(DISTINCT d.symbol) AS count
            FROM daily_bars d
            LEFT JOIN stock_universe u ON u.symbol = d.symbol
            WHERE d.adjust = 'qfq' AND {eligible_daily_bars}
            """
        ).fetchone()
        short_row = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM (
                SELECT d.symbol, COUNT(*) AS bars
                FROM daily_bars d
                LEFT JOIN stock_universe u ON u.symbol = d.symbol
                WHERE d.adjust = 'qfq' AND {eligible_daily_bars}
                GROUP BY d.symbol
                HAVING COUNT(*) < 120
            ) short_history
            """
        ).fetchone()
        stale_row = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM (
                SELECT d.symbol, MAX(d.trade_date) AS latest_symbol_day
                FROM daily_bars d
                LEFT JOIN stock_universe u ON u.symbol = d.symbol
                WHERE d.adjust = 'qfq' AND {eligible_daily_bars}
                GROUP BY d.symbol
            ) latest_by_symbol
            WHERE %s::date IS NOT NULL
              AND latest_symbol_day < %s::date
            """,
            (latest_day, latest_day),
        ).fetchone()
        if latest_day:
            latest_count_row = conn.execute(
                f"""
                SELECT COUNT(DISTINCT d.symbol) AS count
                FROM daily_bars d
                LEFT JOIN stock_universe u ON u.symbol = d.symbol
                WHERE d.adjust = 'qfq' AND d.trade_date = %s AND {eligible_daily_bars}
                """,
                (latest_day,),
            ).fetchone()
            zero_amount_row = conn.execute(
                f"""
                SELECT COUNT(DISTINCT d.symbol) AS count
                FROM daily_bars d
                LEFT JOIN stock_universe u ON u.symbol = d.symbol
                WHERE d.adjust = 'qfq'
                  AND d.trade_date = %s
                  AND d.amount <= 0
                  AND {eligible_daily_bars}
                """,
                (latest_day,),
            ).fetchone()
        else:
            latest_count_row = {"count": 0}
            zero_amount_row = {"count": 0}
    return StealthDataQualitySummary(
        latest_trade_date=latest_day,
        universe_symbols=int(universe_row["count"] or 0) if universe_row else 0,
        symbols_with_bars=int(symbols_row["count"] or 0) if symbols_row else 0,
        latest_bar_symbols=int(latest_count_row["count"] or 0) if latest_count_row else 0,
        zero_amount_symbols=int(zero_amount_row["count"] or 0) if zero_amount_row else 0,
        short_history_symbols=int(short_row["count"] or 0) if short_row else 0,
        stale_symbols=int(stale_row["count"] or 0) if stale_row else 0,
        checked_at=datetime.now(timezone.utc),
    )


def _scan_alerts(
    *,
    latest_tasks: list[StealthScanTask],
    running_task: StealthScanTask | None,
    latest_failure_rate: float,
    unresolved_failures: int,
    data_quality: StealthDataQualitySummary,
) -> list[StealthScanAlert]:
    alerts: list[StealthScanAlert] = []
    latest = latest_tasks[0] if latest_tasks else None
    if latest and latest.status == "failed":
        alerts.append(StealthScanAlert(level="critical", metric="latest_task", value=latest.id, message="最近一次扫描任务整体失败。"))
    if latest_failure_rate >= 0.2:
        alerts.append(StealthScanAlert(level="critical", metric="failure_rate", value=round(latest_failure_rate, 4), message="最近完成任务失败率超过 20%。"))
    elif latest_failure_rate >= 0.05:
        alerts.append(StealthScanAlert(level="warning", metric="failure_rate", value=round(latest_failure_rate, 4), message="最近完成任务存在可关注的单票失败。"))
    if unresolved_failures > 0:
        alerts.append(StealthScanAlert(level="warning", metric="unresolved_failures", value=unresolved_failures, message="仍有未恢复的失败股票，可重跑失败项。"))
    if running_task and (datetime.now(timezone.utc) - running_task.updated_at).total_seconds() > 300:
        alerts.append(StealthScanAlert(level="warning", metric="running_task_stale", value=running_task.id, message="运行中的扫描任务超过 5 分钟没有进度更新。"))
    if data_quality.latest_trade_date is None:
        alerts.append(StealthScanAlert(level="critical", metric="latest_trade_date", message="尚未写入任何日线数据。"))
    if data_quality.zero_amount_symbols > 0:
        alerts.append(StealthScanAlert(level="warning", metric="zero_amount_symbols", value=data_quality.zero_amount_symbols, message="最新交易日存在成交额为 0 的记录。"))
    if data_quality.stale_symbols > 0:
        alerts.append(StealthScanAlert(level="warning", metric="stale_symbols", value=data_quality.stale_symbols, message="部分股票最新日线落后于当前数据集最新交易日。"))
    if data_quality.short_history_symbols > 0:
        alerts.append(StealthScanAlert(level="info", metric="short_history_symbols", value=data_quality.short_history_symbols, message="部分股票历史 K 线不足 120 根，会被策略自动降权或排除。"))
    return alerts


def mark_unfinished_scan_tasks_failed() -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE stealth_scan_tasks
            SET status = 'failed',
                error = COALESCE(error, '服务重启，未完成的扫描任务已停止。'),
                message = '服务重启，未完成的扫描任务已停止。',
                finished_at = COALESCE(finished_at, NOW()),
                updated_at = NOW()
            WHERE status IN ('queued', 'running')
            """
        )


def latest_trading_day() -> date | None:
    with connect() as conn:
        row = conn.execute(
            f"SELECT MAX(trading_day) AS trading_day FROM stealth_scan_results WHERE {mainboard_symbol_sql('symbol')} AND UPPER(name) NOT LIKE '%%ST%%' AND name NOT LIKE '%%退%%'"
        ).fetchone()
    return row["trading_day"] if row and row["trading_day"] else None


def list_candidates(
    stage: str | None = None,
    min_score: float = 0,
    limit: int = 50,
    trading_day: date | None = None,
    user_id: str = DEFAULT_USER_ID,
    include_insufficient: bool = False,
    diagnostic_only: bool = False,
    suppress_repeats: bool = False,
    repeat_days: int = 3,
) -> list[StealthCandidate]:
    day = trading_day or latest_trading_day()
    if day is None:
        return []
    params: list[Any] = [user_id, day, min_score]
    where = (
        f"r.trading_day = %s AND r.total_score >= %s AND {mainboard_symbol_sql('r.symbol')} "
        "AND UPPER(r.name) NOT LIKE '%%ST%%' AND r.name NOT LIKE '%%退%%'"
    )
    if stage:
        where += " AND r.stage = %s"
        params.append(stage)
    elif diagnostic_only:
        where += " AND r.stage = '数据不足'"
    elif not include_insufficient:
        where += " AND r.stage <> '数据不足'"
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT r.*, COALESCE(array_agg(t.theme_name) FILTER (WHERE t.theme_name IS NOT NULL), ARRAY[]::TEXT[]) AS themes,
                   o.symbol IS NOT NULL AS observed
            FROM stealth_scan_results r
            LEFT JOIN theme_memberships t ON t.symbol = r.symbol
            LEFT JOIN observation_list o ON o.user_id = %s AND o.symbol = r.symbol
            WHERE {where}
            GROUP BY r.trading_day, r.symbol, o.symbol
            ORDER BY r.total_score DESC, r.launch_score DESC, r.accumulation_score DESC
            LIMIT %s
            """,
            tuple(params),
        ).fetchall()
    candidates = [_candidate_from_row(row) for row in rows]
    if suppress_repeats and not stage and not diagnostic_only:
        candidates = _suppress_repeated_candidates(candidates, day, repeat_days=max(2, repeat_days), user_id=user_id)
    return candidates


def _suppress_repeated_candidates(
    candidates: list[StealthCandidate],
    trading_day: date,
    *,
    repeat_days: int,
    user_id: str,
) -> list[StealthCandidate]:
    symbols = [candidate.symbol for candidate in candidates if not candidate.observed]
    if not symbols:
        return candidates
    with connect() as conn:
        rows = conn.execute(
            """
            WITH recent_days AS (
                SELECT DISTINCT trading_day
                FROM stealth_scan_results
                WHERE trading_day <= %s
                ORDER BY trading_day DESC
                LIMIT %s
            )
            SELECT r.symbol, r.stage, r.trading_day, o.symbol IS NOT NULL AS observed
            FROM stealth_scan_results r
            LEFT JOIN observation_list o ON o.user_id = %s AND o.symbol = r.symbol
            WHERE r.symbol = ANY(%s) AND r.trading_day IN (SELECT trading_day FROM recent_days)
            ORDER BY r.symbol, r.trading_day ASC
            """,
            (trading_day, repeat_days, user_id, symbols),
        ).fetchall()
    history: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        history.setdefault(row["symbol"], []).append(row)

    visible: list[StealthCandidate] = []
    for candidate in candidates:
        if candidate.observed:
            visible.append(candidate)
            continue
        rows_for_symbol = history.get(candidate.symbol, [])
        days = {row["trading_day"] for row in rows_for_symbol}
        same_stage = all(row["stage"] == candidate.stage for row in rows_for_symbol)
        observed_any = any(bool(row["observed"]) for row in rows_for_symbol)
        if len(days) >= repeat_days and same_stage and not observed_any:
            continue
        visible.append(candidate)
    return visible


def get_candidate(symbol: str, user_id: str = DEFAULT_USER_ID) -> StealthCandidate | None:
    day = latest_trading_day()
    if day is None:
        return None
    rows = list_candidates(limit=1000, trading_day=day, user_id=user_id, include_insufficient=True)
    normalized = symbol.upper()
    return next((candidate for candidate in rows if candidate.symbol == normalized), None)


def list_strategy_diagnostics(limit: int = 30, min_score: float = 20, user_id: str = DEFAULT_USER_ID) -> list[StealthCandidate]:
    return list_candidates(
        min_score=min_score,
        limit=limit,
        user_id=user_id,
        include_insufficient=True,
        diagnostic_only=True,
    )


def list_daily_bars(symbol: str, limit: int = 250) -> list[DailyBar]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM daily_bars
            WHERE symbol = %s AND adjust = 'qfq'
            ORDER BY trade_date DESC
            LIMIT %s
            """,
            (symbol.upper(), limit),
        ).fetchall()
    return [
        DailyBar(
            symbol=row["symbol"],
            trade_date=row["trade_date"],
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            amount=float(row["amount"]),
            change_pct=float(row["change_pct"]),
            turnover_rate=float(row["turnover_rate"]),
            adjust=row["adjust"],
        )
        for row in reversed(rows)
    ]


def observe_symbol(
    symbol: str,
    reason: str = "",
    note: str = "",
    invalidation_rule: str = "",
    next_focus: str = "",
    user_id: str = DEFAULT_USER_ID,
) -> ObservationItem:
    normalized = symbol.upper()
    if not is_mainboard_symbol(normalized):
        raise ValueError("仅允许将沪深主板、非 ST 标的加入观察池。")
    with connect() as conn:
        metadata = conn.execute(
            """
            SELECT BOOL_OR(blocked) AS blocked
            FROM (
                SELECT is_st OR UPPER(name) LIKE '%%ST%%' OR name LIKE '%%退%%' AS blocked
                FROM stock_universe
                WHERE symbol = %s
                UNION ALL
                SELECT UPPER(name) LIKE '%%ST%%' OR name LIKE '%%退%%' AS blocked
                FROM stealth_scan_results
                WHERE symbol = %s
            ) known_status
            """,
            (normalized, normalized),
        ).fetchone()
    if not metadata or metadata["blocked"] is not False:
        raise ValueError("仅允许将沪深主板、非 ST 标的加入观察池。")
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO observation_list (user_id, symbol, reason, note, invalidation_rule, next_focus)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, symbol) DO UPDATE SET
                reason = EXCLUDED.reason,
                note = EXCLUDED.note,
                invalidation_rule = EXCLUDED.invalidation_rule,
                next_focus = EXCLUDED.next_focus,
                status = '观察中',
                updated_at = NOW()
            RETURNING symbol, reason, status, note, invalidation_rule, next_focus, created_at, updated_at
            """,
            (user_id, normalized, reason, note, invalidation_rule, next_focus),
        ).fetchone()
    return next((item for item in list_observations(user_id) if item.symbol == normalized), _observation_from_row(row))


def delete_observation(symbol: str, user_id: str = DEFAULT_USER_ID) -> bool:
    with connect() as conn:
        cursor = conn.execute(
            "DELETE FROM observation_list WHERE user_id = %s AND symbol = %s",
            (user_id, symbol.upper()),
        )
    return bool(cursor.rowcount)


def list_observations(user_id: str = DEFAULT_USER_ID) -> list[ObservationItem]:
    with connect() as conn:
        rows = conn.execute(
            f"""
            WITH latest AS (
                SELECT MAX(trading_day) AS trading_day
                FROM stealth_scan_results
                WHERE {mainboard_symbol_sql('symbol')}
                  AND UPPER(name) NOT LIKE '%%ST%%'
                  AND name NOT LIKE '%%退%%'
            )
            SELECT
                o.symbol AS observation_symbol,
                o.reason,
                o.status,
                o.note,
                o.invalidation_rule,
                o.next_focus,
                o.created_at,
                o.updated_at,
                EXTRACT(DAY FROM (NOW() - o.created_at))::INTEGER AS days_observed,
                r.trading_day,
                r.symbol AS candidate_symbol,
                r.name,
                r.stage,
                r.total_score,
                r.accumulation_score,
                r.launch_score,
                r.theme_score,
                r.risk_penalty,
                r.evidence,
                r.risks,
                r.metrics,
                COALESCE(t.themes, ARRAY[]::TEXT[]) AS themes,
                r.source_ids,
                TRUE AS observed
            FROM observation_list o
            LEFT JOIN latest l ON TRUE
            LEFT JOIN stealth_scan_results r
                ON r.symbol = o.symbol
               AND r.trading_day = l.trading_day
               AND UPPER(r.name) NOT LIKE '%%ST%%'
               AND r.name NOT LIKE '%%退%%'
            LEFT JOIN LATERAL (
                SELECT array_agg(tm.theme_name) AS themes
                FROM theme_memberships tm
                WHERE tm.symbol = o.symbol
            ) t ON TRUE
            LEFT JOIN stock_universe u ON u.symbol = o.symbol
            WHERE o.user_id = %s
              AND {mainboard_symbol_sql('o.symbol')}
              AND (
                  u.symbol IS NOT NULL
                  OR EXISTS (
                      SELECT 1 FROM stealth_scan_results known
                      WHERE known.symbol = o.symbol
                  )
              )
              AND COALESCE(u.is_st, FALSE) = FALSE
              AND UPPER(COALESCE(u.name, '')) NOT LIKE '%%ST%%'
              AND COALESCE(u.name, '') NOT LIKE '%%退%%'
              AND NOT EXISTS (
                  SELECT 1
                  FROM stealth_scan_results blocked
                  WHERE blocked.symbol = o.symbol
                    AND (UPPER(blocked.name) LIKE '%%ST%%' OR blocked.name LIKE '%%退%%')
              )
            ORDER BY o.updated_at DESC
            """,
            (user_id,),
        ).fetchall()
    return [_observation_from_row(row) for row in rows]


def build_observation_summary(user_id: str = DEFAULT_USER_ID) -> ObservationSummary:
    observations = list_observations(user_id)
    buckets: dict[str, list[ObservationItem]] = {
        "activation": [],
        "continue": [],
        "invalid": [],
        "data_gap": [],
    }
    for item in observations:
        buckets[_observation_bucket_key(item)].append(item)

    updated_at = max((item.updated_at for item in observations), default=datetime.now(timezone.utc))
    return ObservationSummary(
        total=len(observations),
        continue_count=len(buckets["continue"]),
        activation_count=len(buckets["activation"]),
        invalid_count=len(buckets["invalid"]),
        data_gap_count=len(buckets["data_gap"]),
        updated_at=updated_at,
        buckets=[
            ObservationSummaryBucket(key="activation", label="启动确认", count=len(buckets["activation"]), items=buckets["activation"][:8]),
            ObservationSummaryBucket(key="continue", label="继续观察", count=len(buckets["continue"]), items=buckets["continue"][:8]),
            ObservationSummaryBucket(key="invalid", label="失效检查", count=len(buckets["invalid"]), items=buckets["invalid"][:8]),
            ObservationSummaryBucket(key="data_gap", label="待补扫", count=len(buckets["data_gap"]), items=buckets["data_gap"][:8]),
        ],
    )


def snapshot_observation_journal(user_id: str = DEFAULT_USER_ID, symbols: list[str] | None = None) -> list[ObservationJournalEntry]:
    target_symbols = {symbol.upper() for symbol in symbols or []}
    observations = [
        item
        for item in list_observations(user_id)
        if not target_symbols or item.symbol in target_symbols
    ]
    if not observations:
        return []

    written: list[ObservationJournalEntry] = []
    with connect() as conn:
        for item in observations:
            bucket_key = _observation_bucket_key(item)
            bucket_label = _observation_bucket_label(bucket_key)
            candidate = item.candidate
            trading_day = candidate.trading_day if candidate else latest_trading_day() or date.today()
            previous = conn.execute(
                """
                SELECT bucket_key, bucket_label
                FROM observation_journal
                WHERE user_id = %s AND symbol = %s AND trading_day < %s
                ORDER BY trading_day DESC
                LIMIT 1
                """,
                (user_id, item.symbol, trading_day),
            ).fetchone()
            previous_key = previous["bucket_key"] if previous else None
            previous_label = previous["bucket_label"] if previous else None
            transition_label = _observation_transition_label(previous_label, bucket_label)
            row = conn.execute(
                """
                INSERT INTO observation_journal (
                    user_id, symbol, trading_day, name, bucket_key, bucket_label,
                    previous_bucket_key, transition_label, stage, total_score,
                    accumulation_score, launch_score, theme_score, risk_penalty,
                    decision_summary, observation_reason, manual_invalidation_rule,
                    next_focus, evidence, risks, invalidation_reasons, source_ids
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, symbol, trading_day) DO UPDATE SET
                    name = EXCLUDED.name,
                    bucket_key = EXCLUDED.bucket_key,
                    bucket_label = EXCLUDED.bucket_label,
                    previous_bucket_key = EXCLUDED.previous_bucket_key,
                    transition_label = EXCLUDED.transition_label,
                    stage = EXCLUDED.stage,
                    total_score = EXCLUDED.total_score,
                    accumulation_score = EXCLUDED.accumulation_score,
                    launch_score = EXCLUDED.launch_score,
                    theme_score = EXCLUDED.theme_score,
                    risk_penalty = EXCLUDED.risk_penalty,
                    decision_summary = EXCLUDED.decision_summary,
                    observation_reason = EXCLUDED.observation_reason,
                    manual_invalidation_rule = EXCLUDED.manual_invalidation_rule,
                    next_focus = EXCLUDED.next_focus,
                    evidence = EXCLUDED.evidence,
                    risks = EXCLUDED.risks,
                    invalidation_reasons = EXCLUDED.invalidation_reasons,
                    source_ids = EXCLUDED.source_ids,
                    updated_at = NOW()
                RETURNING *
                """,
                (
                    user_id,
                    item.symbol,
                    trading_day,
                    candidate.name if candidate else "",
                    bucket_key,
                    bucket_label,
                    previous_key,
                    transition_label,
                    candidate.stage if candidate else "待补扫",
                    candidate.total_score if candidate else None,
                    candidate.accumulation_score if candidate else None,
                    candidate.launch_score if candidate else None,
                    candidate.theme_score if candidate else None,
                    candidate.risk_penalty if candidate else None,
                    _observation_decision_summary(item, bucket_label),
                    item.reason,
                    item.invalidation_rule,
                    item.next_focus,
                    _json(candidate.evidence if candidate else []),
                    _json(candidate.risks if candidate else []),
                    _json(item.invalidation_reasons),
                    _json(candidate.source_ids if candidate else []),
                ),
            ).fetchone()
            written.append(_observation_journal_from_row(row))
    return written


def list_observation_journal(
    user_id: str = DEFAULT_USER_ID,
    symbol: str | None = None,
    limit: int = 80,
) -> list[ObservationJournalEntry]:
    params: list[Any] = [user_id]
    where = f"user_id = %s AND {mainboard_symbol_sql('symbol')} AND UPPER(name) NOT LIKE '%%ST%%' AND name NOT LIKE '%%退%%'"
    if symbol:
        where += " AND symbol = %s"
        params.append(symbol.upper())
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM observation_journal
            WHERE {where}
            ORDER BY trading_day DESC, updated_at DESC, symbol ASC
            LIMIT %s
            """,
            tuple(params),
        ).fetchall()
    return [_observation_journal_from_row(row) for row in rows]


def _observation_bucket_key(item: ObservationItem) -> str:
    candidate = item.candidate
    if candidate is None:
        return "data_gap"
    if candidate.stage == "启动确认" or candidate.launch_score >= 65:
        return "activation"
    if (
        candidate.stage == "过热排除"
        or candidate.stage == "数据不足"
        or candidate.risk_penalty >= 35
        or candidate.total_score < 35
    ):
        return "invalid"
    return "continue"


def _observation_bucket_label(bucket_key: str) -> str:
    return {
        "activation": "启动确认",
        "continue": "继续观察",
        "invalid": "失效检查",
        "data_gap": "待补扫",
    }.get(bucket_key, "继续观察")


def _observation_transition_label(previous_label: str | None, current_label: str) -> str:
    if previous_label is None:
        return f"首次记录为{current_label}"
    if previous_label == current_label:
        return f"{current_label}延续"
    return f"{previous_label} → {current_label}"


def _observation_decision_summary(item: ObservationItem, bucket_label: str) -> str:
    candidate = item.candidate
    manual_parts: list[str] = []
    if item.reason:
        manual_parts.append(f"观察理由：{item.reason}")
    if item.invalidation_rule:
        manual_parts.append(f"人工失效条件：{item.invalidation_rule}")
    if item.next_focus:
        manual_parts.append(f"下次重点：{item.next_focus}")
    manual_text = " ".join(manual_parts)
    if candidate is None:
        base = "最新扫描尚未覆盖该股票，先补扫再判断观察状态。"
        return f"{base} {manual_text}".strip()
    score_line = (
        f"{bucket_label}：阶段 {candidate.stage}，总分 {candidate.total_score:.0f}，"
        f"潜伏 {candidate.accumulation_score:.0f} / 启动 {candidate.launch_score:.0f} / 题材 {candidate.theme_score:.0f}。"
    )
    if item.invalidation_reasons:
        return f"{score_line} 失效条件：{item.invalidation_reasons[0]} {manual_text}".strip()
    if candidate.evidence:
        return f"{score_line} 主要依据：{candidate.evidence[0]} {manual_text}".strip()
    return f"{score_line} {manual_text}".strip()


def _observation_journal_from_row(row: dict[str, Any]) -> ObservationJournalEntry:
    return ObservationJournalEntry(
        symbol=row["symbol"],
        trading_day=row["trading_day"],
        name=row["name"] or "",
        bucket_key=row["bucket_key"],
        bucket_label=row["bucket_label"],
        previous_bucket_key=row["previous_bucket_key"],
        transition_label=row["transition_label"],
        stage=row["stage"] or "",
        total_score=float(row["total_score"]) if row["total_score"] is not None else None,
        accumulation_score=float(row["accumulation_score"]) if row["accumulation_score"] is not None else None,
        launch_score=float(row["launch_score"]) if row["launch_score"] is not None else None,
        theme_score=float(row["theme_score"]) if row["theme_score"] is not None else None,
        risk_penalty=float(row["risk_penalty"]) if row["risk_penalty"] is not None else None,
        decision_summary=row["decision_summary"],
        observation_reason=row.get("observation_reason") or "",
        manual_invalidation_rule=row.get("manual_invalidation_rule") or "",
        next_focus=row.get("next_focus") or "",
        evidence=row["evidence"] or [],
        risks=row["risks"] or [],
        invalidation_reasons=row["invalidation_reasons"] or [],
        source_ids=row["source_ids"] or [],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _candidate_from_row(row: dict[str, Any]) -> StealthCandidate:
    return StealthCandidate(
        trading_day=row["trading_day"],
        symbol=row["symbol"],
        name=row["name"],
        stage=row["stage"],
        total_score=float(row["total_score"]),
        accumulation_score=float(row["accumulation_score"]),
        launch_score=float(row["launch_score"]),
        theme_score=float(row["theme_score"]),
        risk_penalty=float(row["risk_penalty"]),
        evidence=row["evidence"] or [],
        risks=row["risks"] or [],
        metrics=row["metrics"] or {},
        themes=list(row["themes"] or []),
        observed=bool(row["observed"]),
        source_ids=row["source_ids"] or ["src-akshare-dev"],
    )


def _observation_from_row(row: dict[str, Any]) -> ObservationItem:
    candidate = _candidate_from_row(
        {
            "trading_day": row["trading_day"],
            "symbol": row["candidate_symbol"],
            "name": row["name"],
            "stage": row["stage"],
            "total_score": row["total_score"],
            "accumulation_score": row["accumulation_score"],
            "launch_score": row["launch_score"],
            "theme_score": row["theme_score"],
            "risk_penalty": row["risk_penalty"],
            "evidence": row["evidence"],
            "risks": row["risks"],
            "metrics": row["metrics"],
            "themes": row["themes"],
            "source_ids": row["source_ids"],
            "observed": True,
        }
    ) if row.get("candidate_symbol") else None
    return ObservationItem(
        symbol=row.get("observation_symbol") or row["symbol"],
        reason=row["reason"],
        status=row["status"],
        note=row["note"],
        invalidation_rule=row.get("invalidation_rule") or "",
        next_focus=row.get("next_focus") or "",
        candidate=candidate,
        invalidation_reasons=_observation_invalidation_reasons(candidate),
        days_observed=int(row.get("days_observed") or 0),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _observation_invalidation_reasons(candidate: StealthCandidate | None) -> list[str]:
    if candidate is None:
        return ["最新扫描未覆盖该股票，需要单票补扫后再判断观察状态。"]
    reasons: list[str] = []
    if candidate.stage == "过热排除":
        reasons.append("最新阶段为过热排除，继续观察前需要确认是否已经脱离合理跟踪区。")
    if candidate.stage == "数据不足" and candidate.total_score < 20:
        reasons.append("最新总分低于观察阈值，暂时缺少足够证据支持继续跟踪。")
    if candidate.risk_penalty >= 35:
        reasons.append("风险扣分偏高，需要优先检查公告、连续涨停或流动性异常。")
    if not reasons and candidate.risks:
        reasons.append(candidate.risks[0])
    return reasons


def _scan_task_from_row(row: dict[str, Any]) -> StealthScanTask:
    return StealthScanTask(
        id=row["id"],
        status=row["status"],
        requested_limit=row["requested_limit"],
        requested_offset=int(row.get("requested_offset") or 0),
        requested_symbols=list(row["requested_symbols"] or []),
        active_themes=list(row["active_themes"] or []),
        total=int(row["total"] or 0),
        scanned=int(row["scanned"] or 0),
        saved=int(row["saved"] or 0),
        failed=int(row["failed"] or 0),
        stages=dict(row["stages"] or {}),
        message=row["message"] or "",
        error=row["error"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        updated_at=row["updated_at"],
    )


def _scan_failure_from_row(row: dict[str, Any]) -> StealthScanFailure:
    return StealthScanFailure(
        id=int(row["id"]),
        task_id=row["task_id"],
        symbol=row["symbol"],
        name=row["name"] or "",
        stage=row["stage"] or "history",
        error=row["error"] or "",
        retry_count=int(row["retry_count"] or 0),
        resolved=bool(row["resolved"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
