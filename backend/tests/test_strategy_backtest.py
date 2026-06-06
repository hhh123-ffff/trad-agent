from datetime import date, timedelta

import pytest

from backend.app.models import DailyBar, StealthCandidate, StockUniverseItem, StrategySignalOutcome
from backend.app.strategy_backtest import (
    aggregate_signal_outcomes,
    calculate_horizon_outcomes,
    deduplicate_signals,
    estimate_float_market_cap_billion,
    replay_symbol_history,
    sync_live_signal_outcomes,
)


def _bar(
    day: date,
    *,
    open_price: float = 10,
    high: float = 10.5,
    low: float = 9.5,
    close: float = 10,
    amount: float = 1_000_000_000,
    turnover_rate: float = 5,
) -> DailyBar:
    return DailyBar(
        symbol="600001.SH",
        trade_date=day,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=100_000_000,
        amount=amount,
        change_pct=4,
        turnover_rate=turnover_rate,
    )


def _outcome(day: date, *, stage: str = "启动确认", symbol: str = "600001.SH") -> StrategySignalOutcome:
    return StrategySignalOutcome(
        id=f"{symbol}-{day}-{stage}",
        origin="replay",
        signal_date=day,
        symbol=symbol,
        name="测试股份",
        stage=stage,
        total_score=80,
    )


def test_estimates_historical_float_market_cap_from_amount_and_turnover():
    assert estimate_float_market_cap_billion(_bar(date(2026, 1, 1))) == 200
    assert estimate_float_market_cap_billion(_bar(date(2026, 1, 1), turnover_rate=0)) is None


def test_calculates_next_open_outcomes_and_marks_immature_horizons():
    start = date(2026, 1, 1)
    bars = [
        _bar(start, close=10),
        _bar(start + timedelta(days=1), open_price=10, high=11, low=9, close=10.5),
        _bar(start + timedelta(days=2), open_price=10.5, high=12, low=10, close=11),
        _bar(start + timedelta(days=3), open_price=11, high=11.5, low=10.5, close=10.8),
    ]

    result = calculate_horizon_outcomes(bars, signal_index=0, benchmark_returns={1: 2, 3: 5})

    assert result["entry_date"] == start + timedelta(days=1)
    assert result["entry_price"] == 10
    assert result["horizons"]["1d"] == {
        "status": "mature",
        "close_return_pct": 5.0,
        "mfe_pct": 10.0,
        "mae_pct": -10.0,
        "benchmark_return_pct": 2.0,
        "excess_return_pct": 3.0,
        "positive": True,
        "outperformed": True,
    }
    assert result["horizons"]["3d"]["close_return_pct"] == pytest.approx(8.0)
    assert result["horizons"]["3d"]["mfe_pct"] == pytest.approx(20.0)
    assert result["horizons"]["3d"]["mae_pct"] == pytest.approx(-10.0)
    assert result["horizons"]["5d"] == {"status": "immature"}
    assert result["horizons"]["10d"] == {"status": "immature"}


def test_marks_invalid_entry_without_fabricating_returns():
    bars = [_bar(date(2026, 1, 1)), _bar(date(2026, 1, 2), open_price=0)]

    result = calculate_horizon_outcomes(bars, signal_index=0)

    assert result["entry_price"] is None
    assert all(item == {"status": "invalid"} for item in result["horizons"].values())


def test_deduplicates_same_stage_within_three_trading_days_and_keeps_upgrade():
    start = date(2026, 1, 1)
    trading_days = [start + timedelta(days=offset) for offset in (0, 1, 2, 5, 6)]
    signals = [
        _outcome(trading_days[0], stage="潜伏观察"),
        _outcome(trading_days[2], stage="潜伏观察"),
        _outcome(trading_days[2], stage="启动确认"),
        _outcome(trading_days[4], stage="潜伏观察"),
    ]

    result = deduplicate_signals(signals, repeat_days=3, trading_days=trading_days)

    assert [item.included_primary for item in result] == [True, False, True, True]
    assert result[1].duplicate_reason
    assert result[2].duplicate_reason == ""


def test_replay_passes_only_history_available_on_each_signal_day():
    start = date(2026, 1, 1)
    bars = [_bar(start + timedelta(days=offset)) for offset in range(125)]
    seen_lengths: list[int] = []

    def recording_evaluator(item, daily_bars, **kwargs):
        seen_lengths.append(len(daily_bars))
        return StealthCandidate(
            trading_day=daily_bars[-1].trade_date,
            symbol=item.symbol,
            name=item.name,
            stage="启动确认" if len(daily_bars) == 120 else "数据不足",
            total_score=80,
            accumulation_score=80,
            launch_score=80,
            theme_score=0,
            risk_penalty=0,
            evidence=[],
            risks=[],
        )

    outcomes, funnel = replay_symbol_history(
        StockUniverseItem(symbol="600001.SH", name="测试股份", listed_days=500),
        bars,
        evaluator=recording_evaluator,
    )

    assert seen_lengths == list(range(120, 126))
    assert len(outcomes) == 1
    assert outcomes[0].signal_date == bars[119].trade_date
    assert outcomes[0].entry_date == bars[120].trade_date
    assert funnel["evaluated_symbol_days"] == 6


def test_aggregates_mature_primary_signals_and_sets_confidence():
    first = _outcome(date(2026, 1, 1))
    first.horizon_outcomes = {
        "5d": {
            "status": "mature",
            "close_return_pct": 8,
            "mfe_pct": 12,
            "mae_pct": -3,
            "benchmark_return_pct": 2,
            "excess_return_pct": 6,
            "positive": True,
            "outperformed": True,
        }
    }
    duplicate = _outcome(date(2026, 1, 2))
    duplicate.included_primary = False
    duplicate.horizon_outcomes = first.horizon_outcomes

    summary = aggregate_signal_outcomes([first, duplicate])

    assert summary["mature_primary_signals"] == 1
    assert summary["confidence"] == "low"
    assert summary["horizons"]["5d"]["median_close_return_pct"] == 8
    assert summary["horizons"]["5d"]["outperformance_rate_pct"] == 100
    assert summary["stages"]["启动确认"]["primary_signals"] == 1


def test_syncs_live_candidates_and_refreshes_mature_outcomes(monkeypatch):
    start = date(2026, 1, 1)
    bars = [
        _bar(start, close=10),
        _bar(start + timedelta(days=1), open_price=10, high=11, low=9.8, close=10.5),
        _bar(start + timedelta(days=2), open_price=10.5, high=11.5, low=10.2, close=11),
    ]
    candidate = StealthCandidate(
        trading_day=start,
        symbol="600001.SH",
        name="测试股份",
        stage="启动确认",
        total_score=82,
        accumulation_score=78,
        launch_score=86,
        theme_score=0,
        risk_penalty=0,
        evidence=["量价结构满足严格条件"],
        risks=[],
    )
    saved: list[StrategySignalOutcome] = []
    monkeypatch.setattr("backend.app.strategy_backtest.list_candidates", lambda **_: [candidate])
    monkeypatch.setattr("backend.app.strategy_backtest.list_daily_bars", lambda *_args, **_kwargs: bars)
    monkeypatch.setattr("backend.app.strategy_backtest.list_signal_outcomes", lambda **_: [])
    monkeypatch.setattr("backend.app.strategy_backtest.save_signal_outcomes", lambda items: saved.extend(items))

    summary = sync_live_signal_outcomes(start)

    assert summary.total_signals == 1
    assert saved[0].origin == "live"
    assert saved[0].backtest_run_id is None
    assert saved[0].entry_date == start + timedelta(days=1)
    assert saved[0].horizon_outcomes["1d"]["status"] == "mature"
    assert saved[0].horizon_outcomes["5d"]["status"] == "immature"


def test_live_sync_does_not_fabricate_outcomes_when_signal_bar_is_missing(monkeypatch):
    signal = _outcome(date(2026, 1, 1))
    signal.origin = "live"
    saved: list[StrategySignalOutcome] = []
    monkeypatch.setattr("backend.app.strategy_backtest.list_candidates", lambda **_: [])
    monkeypatch.setattr("backend.app.strategy_backtest.list_signal_outcomes", lambda **_: [signal])
    monkeypatch.setattr("backend.app.strategy_backtest.list_daily_bars", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("backend.app.strategy_backtest.save_signal_outcomes", lambda items: saved.extend(items))

    sync_live_signal_outcomes(date(2026, 1, 2))

    assert saved[0].entry_price is None
    assert saved[0].horizon_outcomes == {}
    assert "信号日日线缺失" in saved[0].limitations
