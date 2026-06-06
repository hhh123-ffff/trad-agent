from datetime import date

from backend.app.database import connect, init_schema
from backend.app.models import DailyBar, StockUniverseItem, StrategyBacktestRequest, StrategySignalOutcome
from backend.app.stealth_repository import save_daily_bars, save_universe_items
from backend.app.strategy_backtest_repository import (
    create_backtest_run,
    get_backtest_detail,
    get_backtest_funnel,
    list_signal_outcomes,
    save_backtest_funnel,
    save_signal_outcomes,
    update_backtest_run,
    load_backtest_dataset,
)


def _delete_run(run_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM strategy_signal_outcomes WHERE backtest_run_id = %s", (run_id,))
        conn.execute("DELETE FROM strategy_backtest_funnel WHERE backtest_run_id = %s", (run_id,))
        conn.execute("DELETE FROM strategy_backtest_runs WHERE id = %s", (run_id,))


def _outcome(run_id: str, *, origin: str = "replay", stage: str = "启动确认") -> StrategySignalOutcome:
    return StrategySignalOutcome(
        id="outcome-1",
        origin=origin,
        backtest_run_id=run_id if origin == "replay" else None,
        strategy_profile="mainboard_volume_price",
        signal_date=date(2026, 5, 20),
        symbol="600000.SH",
        name="测试股票",
        stage=stage,
        total_score=78,
        accumulation_score=72,
        launch_score=84,
        theme_score=0,
        risk_penalty=0,
        entry_date=date(2026, 5, 21),
        entry_price=10,
        signal_close=9.8,
        included_primary=True,
        sample_quality="estimated_float_cap",
        metrics={"float_cap_source": "estimated_from_turnover"},
        horizon_outcomes={"5": {"maturity": "mature", "close_return_pct": 6.2}},
        source_ids=["src-local-daily-bars"],
        limitations=["历史流通市值为估算值"],
    )


def test_backtest_repository_persists_run_signals_and_funnel_idempotently():
    init_schema()
    run = create_backtest_run(StrategyBacktestRequest(start_date=date(2026, 5, 1), end_date=date(2026, 5, 31)))

    try:
        update_backtest_run(
            run.id,
            status="completed",
            total_symbols=12,
            evaluated_symbol_days=100,
            raw_signals=2,
            primary_signals=1,
            mature_signals=1,
            progress=1,
            summary={"confidence": "low", "horizons": {"5": {"mature_samples": 1}}},
            data_quality={"symbols": 12},
            limitations=["样本量不足"],
            finished=True,
        )
        outcome = _outcome(run.id)
        save_signal_outcomes([outcome, outcome.model_copy(update={"total_score": 81})])
        save_backtest_funnel(run.id, {"available_symbol_days": 100, "strict_signals": 2, "primary_signals": 1})

        detail = get_backtest_detail(run.id)
        signals = list_signal_outcomes(backtest_run_id=run.id, origin="replay", primary_only=True)
        funnel = get_backtest_funnel(run.id)

        assert detail is not None
        assert detail.run.status == "completed"
        assert detail.run.summary["confidence"] == "low"
        assert detail.run.limitations == ["样本量不足"]
        assert len(signals) == 1
        assert signals[0].total_score == 81
        assert signals[0].horizon_outcomes["5"]["close_return_pct"] == 6.2
        assert funnel is not None
        assert funnel.counts["available_symbol_days"] == 100
    finally:
        _delete_run(run.id)


def test_backtest_repository_keeps_live_signals_separate():
    init_schema()
    run = create_backtest_run(StrategyBacktestRequest())

    try:
        replay = _outcome(run.id)
        live = replay.model_copy(update={"id": "live-1", "origin": "live", "backtest_run_id": None})
        save_signal_outcomes([replay, live])

        assert len(list_signal_outcomes(backtest_run_id=run.id, origin="replay")) == 1
        live_results = list_signal_outcomes(origin="live")
        assert len(live_results) == 1
        assert live_results[0].backtest_run_id is None
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM strategy_signal_outcomes WHERE origin = 'live' AND symbol = '600000.SH'")
        _delete_run(run.id)


def test_backtest_dataset_excludes_non_mainboard_and_st_symbols():
    init_schema()
    items = [
        StockUniverseItem(symbol="600099.SH", name="主板样本"),
        StockUniverseItem(symbol="300099.SZ", name="创业板样本"),
        StockUniverseItem(symbol="688099.SH", name="科创板样本"),
        StockUniverseItem(symbol="920099.BJ", name="北交所样本"),
        StockUniverseItem(symbol="600098.SH", name="ST样本", is_st=True),
    ]
    bars = [
        DailyBar(symbol=item.symbol, trade_date=date(2026, 5, 20), open=10, high=11, low=9, close=10)
        for item in items
    ]
    unknown_symbol = "600093.SH"
    bars.append(DailyBar(symbol=unknown_symbol, trade_date=date(2026, 5, 20), open=10, high=11, low=9, close=10))
    save_universe_items(items)
    save_daily_bars(bars)
    try:
        dataset = load_backtest_dataset(StrategyBacktestRequest())
        symbols = {item.symbol for item, _ in dataset}
        assert "600099.SH" in symbols
        assert symbols.isdisjoint({"300099.SZ", "688099.SH", "920099.BJ", "600098.SH", unknown_symbol})
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM daily_bars WHERE symbol = ANY(%s)", ([item.symbol for item in items],))
            conn.execute("DELETE FROM daily_bars WHERE symbol = %s", (unknown_symbol,))
            conn.execute("DELETE FROM stock_universe WHERE symbol = ANY(%s)", ([item.symbol for item in items],))
