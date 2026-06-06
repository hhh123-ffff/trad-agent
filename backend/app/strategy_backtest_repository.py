from __future__ import annotations

from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from .database import connect
from .models import (
    DailyBar,
    StockUniverseItem,
    StrategyBacktestDetail,
    StrategyBacktestFunnel,
    StrategyBacktestRequest,
    StrategyBacktestRun,
    StrategySignalOutcome,
)


def _json(value: Any) -> Jsonb:
    return Jsonb(value)


def create_backtest_run(request: StrategyBacktestRequest) -> StrategyBacktestRun:
    run_id = uuid4().hex
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO strategy_backtest_runs (
                id, status, start_date, end_date, repeat_days, requested_symbols, message
            ) VALUES (%s, 'queued', %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (run_id, request.start_date, request.end_date, request.repeat_days, _json([s.upper() for s in request.symbols]), "回测任务已排队。"),
        ).fetchone()
    return _run(row)


def update_backtest_run(run_id: str, *, started: bool = False, finished: bool = False, **updates: Any) -> StrategyBacktestRun | None:
    allowed = {
        "status", "total_symbols", "total_symbol_days", "evaluated_symbol_days", "raw_signals",
        "primary_signals", "mature_signals", "progress", "summary", "data_quality",
        "limitations", "message", "error",
    }
    assignments = ["updated_at = NOW()"]
    values: list[Any] = []
    for key, value in updates.items():
        if key not in allowed:
            continue
        assignments.append(f"{key} = %s")
        values.append(_json(value) if key in {"summary", "data_quality", "limitations"} else value)
    if started:
        assignments.append("started_at = COALESCE(started_at, NOW())")
    if finished:
        assignments.append("finished_at = NOW()")
    values.append(run_id)
    with connect() as conn:
        row = conn.execute(
            f"UPDATE strategy_backtest_runs SET {', '.join(assignments)} WHERE id = %s RETURNING *",
            tuple(values),
        ).fetchone()
    return _run(row) if row else None


def get_backtest_run(run_id: str) -> StrategyBacktestRun | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM strategy_backtest_runs WHERE id = %s", (run_id,)).fetchone()
    return _run(row) if row else None


def get_latest_backtest_run() -> StrategyBacktestRun | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM strategy_backtest_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    return _run(row) if row else None


def load_backtest_dataset(request: StrategyBacktestRequest) -> list[tuple[StockUniverseItem, list[DailyBar]]]:
    where = ["d.adjust = 'qfq'"]
    values: list[Any] = []
    if request.symbols:
        where.append("d.symbol = ANY(%s)")
        values.append([symbol.upper() for symbol in request.symbols])
    if request.end_date:
        where.append("d.trade_date <= %s")
        values.append(request.end_date)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                d.*,
                COALESCE(u.name, d.symbol) AS name,
                COALESCE(u.is_st, FALSE) AS is_st,
                COALESCE(u.listed_days, 0) AS listed_days,
                COALESCE(u.market, 'A股') AS market
            FROM daily_bars d
            LEFT JOIN stock_universe u ON u.symbol = d.symbol
            WHERE {' AND '.join(where)}
            ORDER BY d.symbol, d.trade_date
            """,
            tuple(values),
        ).fetchall()
    grouped: dict[str, tuple[StockUniverseItem, list[DailyBar]]] = {}
    for row in rows:
        if row["symbol"] not in grouped:
            grouped[row["symbol"]] = (
                StockUniverseItem(
                    symbol=row["symbol"],
                    name=row["name"],
                    is_st=bool(row["is_st"]),
                    listed_days=int(row["listed_days"]),
                    market=row["market"],
                ),
                [],
            )
        grouped[row["symbol"]][1].append(
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
        )
    return list(grouped.values())


def save_signal_outcomes(outcomes: list[StrategySignalOutcome]) -> None:
    with connect() as conn:
        for item in outcomes:
            conn.execute(
                """
                INSERT INTO strategy_signal_outcomes (
                    id, origin, backtest_run_id, strategy_profile, signal_date, symbol, name, stage,
                    total_score, accumulation_score, launch_score, theme_score, risk_penalty,
                    entry_date, entry_price, signal_close, included_primary, duplicate_reason,
                    sample_quality, metrics, horizon_outcomes, source_ids, limitations
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (id) DO UPDATE SET
                    total_score = EXCLUDED.total_score,
                    accumulation_score = EXCLUDED.accumulation_score,
                    launch_score = EXCLUDED.launch_score,
                    theme_score = EXCLUDED.theme_score,
                    risk_penalty = EXCLUDED.risk_penalty,
                    entry_date = EXCLUDED.entry_date,
                    entry_price = EXCLUDED.entry_price,
                    signal_close = EXCLUDED.signal_close,
                    included_primary = EXCLUDED.included_primary,
                    duplicate_reason = EXCLUDED.duplicate_reason,
                    sample_quality = EXCLUDED.sample_quality,
                    metrics = EXCLUDED.metrics,
                    horizon_outcomes = EXCLUDED.horizon_outcomes,
                    source_ids = EXCLUDED.source_ids,
                    limitations = EXCLUDED.limitations,
                    updated_at = NOW()
                """,
                (
                    item.id, item.origin, item.backtest_run_id, item.strategy_profile, item.signal_date,
                    item.symbol, item.name, item.stage, item.total_score, item.accumulation_score,
                    item.launch_score, item.theme_score, item.risk_penalty, item.entry_date,
                    item.entry_price, item.signal_close, item.included_primary, item.duplicate_reason,
                    item.sample_quality, _json(item.metrics), _json(item.horizon_outcomes),
                    _json(item.source_ids), _json(item.limitations),
                ),
            )


def list_signal_outcomes(
    *,
    backtest_run_id: str | None = None,
    origin: str | None = None,
    stage: str | None = None,
    primary_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[StrategySignalOutcome]:
    where: list[str] = []
    values: list[Any] = []
    if backtest_run_id is not None:
        where.append("backtest_run_id = %s")
        values.append(backtest_run_id)
    if origin:
        where.append("origin = %s")
        values.append(origin)
    if stage:
        where.append("stage = %s")
        values.append(stage)
    if primary_only:
        where.append("included_primary = TRUE")
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    values.extend([limit, offset])
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM strategy_signal_outcomes {clause} ORDER BY signal_date DESC, total_score DESC LIMIT %s OFFSET %s",
            tuple(values),
        ).fetchall()
    return [_outcome(row) for row in rows]


def save_backtest_funnel(run_id: str, counts: dict[str, int]) -> StrategyBacktestFunnel:
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO strategy_backtest_funnel (backtest_run_id, counts)
            VALUES (%s, %s)
            ON CONFLICT (backtest_run_id) DO UPDATE SET counts = EXCLUDED.counts, updated_at = NOW()
            RETURNING *
            """,
            (run_id, _json(counts)),
        ).fetchone()
    return _funnel(row)


def get_backtest_funnel(run_id: str) -> StrategyBacktestFunnel | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM strategy_backtest_funnel WHERE backtest_run_id = %s", (run_id,)).fetchone()
    return _funnel(row) if row else None


def get_backtest_detail(run_id: str) -> StrategyBacktestDetail | None:
    run = get_backtest_run(run_id)
    return StrategyBacktestDetail(run=run, funnel=get_backtest_funnel(run_id)) if run else None


def mark_unfinished_backtests_failed() -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE strategy_backtest_runs
            SET status = 'failed', error = COALESCE(error, '服务重启，未完成回测已停止。'),
                message = '服务重启，未完成回测已停止。', finished_at = NOW(), updated_at = NOW()
            WHERE status IN ('queued', 'running')
            """
        )


def _run(row: dict[str, Any]) -> StrategyBacktestRun:
    return StrategyBacktestRun(**row)


def _outcome(row: dict[str, Any]) -> StrategySignalOutcome:
    return StrategySignalOutcome(
        **{
            **row,
            "total_score": float(row["total_score"]),
            "accumulation_score": float(row["accumulation_score"]),
            "launch_score": float(row["launch_score"]),
            "theme_score": float(row["theme_score"]),
            "risk_penalty": float(row["risk_penalty"]),
            "entry_price": float(row["entry_price"]) if row["entry_price"] is not None else None,
            "signal_close": float(row["signal_close"]) if row["signal_close"] is not None else None,
        }
    )


def _funnel(row: dict[str, Any]) -> StrategyBacktestFunnel:
    return StrategyBacktestFunnel(**row)
