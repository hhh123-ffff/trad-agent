from datetime import date, timedelta

from backend.app.database import connect, init_schema
from backend.app.models import DailyBar, StockUniverseItem, StrategyBacktestRequest, StrategySignalOutcome
from backend.app.strategy_backtest_repository import (
    create_backtest_run,
    get_backtest_run,
    list_signal_outcomes,
    mark_unfinished_backtests_failed,
)
from backend.app.strategy_backtest_tasks import run_strategy_backtest_task


def _bars(symbol: str) -> list[DailyBar]:
    start = date(2025, 1, 1)
    return [
        DailyBar(
            symbol=symbol,
            trade_date=start + timedelta(days=offset),
            open=10,
            high=10.5,
            low=9.5,
            close=10,
            volume=100_000_000,
            amount=1_000_000_000,
            change_pct=4,
            turnover_rate=5,
        )
        for offset in range(125)
    ]


def _outcome(run_id: str, symbol: str) -> StrategySignalOutcome:
    return StrategySignalOutcome(
        id=f"replay-{run_id}-{symbol}",
        origin="replay",
        backtest_run_id=run_id,
        signal_date=date(2026, 1, 1),
        symbol=symbol,
        name=symbol,
        stage="启动确认",
        total_score=80,
        included_primary=True,
        horizon_outcomes={"5d": {"status": "mature", "close_return_pct": 5, "mfe_pct": 8, "mae_pct": -2}},
    )


def _delete_run(run_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM strategy_signal_outcomes WHERE backtest_run_id = %s", (run_id,))
        conn.execute("DELETE FROM strategy_backtest_funnel WHERE backtest_run_id = %s", (run_id,))
        conn.execute("DELETE FROM strategy_backtest_runs WHERE id = %s", (run_id,))


def test_background_backtest_continues_after_symbol_failure_and_is_idempotent(monkeypatch):
    init_schema()
    request = StrategyBacktestRequest()
    run = create_backtest_run(request)
    dataset = [
        (StockUniverseItem(symbol="600001.SH", name="甲", listed_days=500), _bars("600001.SH")),
        (StockUniverseItem(symbol="600002.SH", name="乙", listed_days=500), _bars("600002.SH")),
    ]
    monkeypatch.setattr("backend.app.strategy_backtest_tasks.load_backtest_dataset", lambda _: dataset)

    def replay(item, bars, repeat_days):
        if item.symbol == "600002.SH":
            raise RuntimeError("broken symbol")
        return [_outcome(run.id, item.symbol)], {"evaluated_symbol_days": 6, "raw_signals": 1, "primary_signals": 1}

    monkeypatch.setattr("backend.app.strategy_backtest_tasks.replay_symbol_history", replay)

    try:
        run_strategy_backtest_task(run.id, request)
        run_strategy_backtest_task(run.id, request)

        completed = get_backtest_run(run.id)
        outcomes = list_signal_outcomes(backtest_run_id=run.id)
        assert completed is not None
        assert completed.status == "completed"
        assert completed.progress == 1
        assert completed.total_symbols == 2
        assert completed.primary_signals == 1
        assert completed.data_quality["failed_symbols"] == 1
        assert len(outcomes) == 1
    finally:
        _delete_run(run.id)


def test_background_backtest_marks_overall_failure(monkeypatch):
    init_schema()
    request = StrategyBacktestRequest()
    run = create_backtest_run(request)
    monkeypatch.setattr(
        "backend.app.strategy_backtest_tasks.load_backtest_dataset",
        lambda _: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    try:
        run_strategy_backtest_task(run.id, request)

        failed = get_backtest_run(run.id)
        assert failed is not None
        assert failed.status == "failed"
        assert "database unavailable" in (failed.error or "")
    finally:
        _delete_run(run.id)


def test_unfinished_backtest_recovery_marks_tasks_failed():
    init_schema()
    run = create_backtest_run(StrategyBacktestRequest())

    try:
        mark_unfinished_backtests_failed()
        recovered = get_backtest_run(run.id)
        assert recovered is not None
        assert recovered.status == "failed"
        assert recovered.finished_at is not None
    finally:
        _delete_run(run.id)
