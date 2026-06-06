from __future__ import annotations

from collections import defaultdict
from datetime import date
from statistics import median
from typing import Any, Callable, Sequence

from .models import DailyBar, StealthCandidate, StockUniverseItem, StrategyLiveOutcomeSummary, StrategySignalOutcome
from .stealth_repository import list_candidates, list_daily_bars
from .stealth_scanner import evaluate_candidate
from .strategy_backtest_repository import list_signal_outcomes, save_signal_outcomes


HORIZONS = (1, 3, 5, 10)
SIGNAL_STAGES = {"潜伏观察", "启动确认"}
HISTORICAL_LIMITATIONS = [
    "历史回放仅使用信号日及之前的日线数据，不包含分钟线条件。",
    "历史流通市值按成交额和换手率估算，可能与当日披露口径存在偏差。",
    "历史主题和 ST 状态数据不完整，结果存在样本偏差。",
]
CandidateEvaluator = Callable[..., StealthCandidate]


def _rounded(value: float) -> float:
    return round(float(value), 4)


def estimate_float_market_cap_billion(bar: DailyBar) -> float | None:
    if bar.amount <= 0 or bar.turnover_rate <= 0:
        return None
    return _rounded(bar.amount / bar.turnover_rate / 1_000_000)


def calculate_horizon_outcomes(
    bars: Sequence[DailyBar],
    signal_index: int,
    benchmark_returns: dict[int, float] | None = None,
) -> dict[str, Any]:
    horizons: dict[str, dict[str, Any]] = {}
    benchmark_returns = benchmark_returns or {}
    entry_index = signal_index + 1
    if entry_index >= len(bars):
        return {
            "entry_date": None,
            "entry_price": None,
            "horizons": {f"{horizon}d": {"status": "immature"} for horizon in HORIZONS},
        }

    entry_bar = bars[entry_index]
    entry_price = float(entry_bar.open)
    if entry_price <= 0:
        return {
            "entry_date": entry_bar.trade_date,
            "entry_price": None,
            "horizons": {f"{horizon}d": {"status": "invalid"} for horizon in HORIZONS},
        }

    for horizon in HORIZONS:
        key = f"{horizon}d"
        window = bars[entry_index : entry_index + horizon]
        if len(window) < horizon:
            horizons[key] = {"status": "immature"}
            continue
        if any(item.close <= 0 or item.high <= 0 or item.low <= 0 for item in window):
            horizons[key] = {"status": "invalid"}
            continue
        close_return = (float(window[-1].close) / entry_price - 1) * 100
        mfe = (max(float(item.high) for item in window) / entry_price - 1) * 100
        mae = (min(float(item.low) for item in window) / entry_price - 1) * 100
        benchmark_return = float(benchmark_returns.get(horizon, 0))
        excess_return = close_return - benchmark_return
        horizons[key] = {
            "status": "mature",
            "close_return_pct": _rounded(close_return),
            "mfe_pct": _rounded(mfe),
            "mae_pct": _rounded(mae),
            "benchmark_return_pct": _rounded(benchmark_return),
            "excess_return_pct": _rounded(excess_return),
            "positive": close_return > 0,
            "outperformed": excess_return > 0,
        }
    return {"entry_date": entry_bar.trade_date, "entry_price": entry_price, "horizons": horizons}


def deduplicate_signals(
    signals: Sequence[StrategySignalOutcome],
    *,
    repeat_days: int = 3,
    trading_days: Sequence[date] | None = None,
) -> list[StrategySignalOutcome]:
    day_positions = {day: index for index, day in enumerate(sorted(set(trading_days or [])))}
    last_primary: dict[tuple[str, str], int | date] = {}
    result: list[StrategySignalOutcome] = []
    ordered_signals = sorted(enumerate(signals), key=lambda pair: (pair[1].signal_date, pair[0]))
    for _, signal in ordered_signals:
        key = (signal.symbol, signal.stage)
        current_position: int | date = day_positions.get(signal.signal_date, signal.signal_date)
        previous = last_primary.get(key)
        is_duplicate = False
        if isinstance(previous, int) and isinstance(current_position, int):
            is_duplicate = current_position - previous <= repeat_days
        elif isinstance(previous, date) and isinstance(current_position, date):
            is_duplicate = (current_position - previous).days <= repeat_days
        if is_duplicate:
            signal.included_primary = False
            signal.duplicate_reason = f"同一阶段在 {repeat_days} 个交易日内已出现"
        else:
            signal.included_primary = True
            signal.duplicate_reason = ""
            last_primary[key] = current_position
        result.append(signal)
    return result


def aggregate_signal_outcomes(outcomes: Sequence[StrategySignalOutcome]) -> dict[str, Any]:
    primary = [item for item in outcomes if item.included_primary]
    horizon_summary: dict[str, dict[str, Any]] = {}
    stage_summary: dict[str, dict[str, Any]] = {}
    mature_primary_ids: set[str] = set()
    for horizon in HORIZONS:
        key = f"{horizon}d"
        mature = [
            item.horizon_outcomes[key]
            for item in primary
            if item.horizon_outcomes.get(key, {}).get("status") == "mature"
        ]
        for item in primary:
            if item.horizon_outcomes.get(key, {}).get("status") == "mature":
                mature_primary_ids.add(item.id)
        if not mature:
            horizon_summary[key] = {"mature_count": 0}
            continue
        close_returns = [float(item["close_return_pct"]) for item in mature]
        benchmark_returns = [float(item.get("benchmark_return_pct", 0)) for item in mature]
        excess_returns = [float(item.get("excess_return_pct", 0)) for item in mature]
        horizon_summary[key] = {
            "mature_count": len(mature),
            "median_close_return_pct": _rounded(median(close_returns)),
            "average_close_return_pct": _rounded(sum(close_returns) / len(close_returns)),
            "median_benchmark_return_pct": _rounded(median(benchmark_returns)),
            "median_excess_return_pct": _rounded(median(excess_returns)),
            "positive_rate_pct": _rounded(sum(bool(item.get("positive")) for item in mature) / len(mature) * 100),
            "outperformance_rate_pct": _rounded(
                sum(bool(item.get("outperformed")) for item in mature) / len(mature) * 100
            ),
            "median_mfe_pct": _rounded(median(float(item["mfe_pct"]) for item in mature)),
            "median_mae_pct": _rounded(median(float(item["mae_pct"]) for item in mature)),
        }
    sample_count = horizon_summary.get("5d", {}).get("mature_count", 0)
    for stage in sorted({item.stage for item in primary}):
        stage_items = [item for item in primary if item.stage == stage]
        mature_5d = [
            item.horizon_outcomes["5d"]
            for item in stage_items
            if item.horizon_outcomes.get("5d", {}).get("status") == "mature"
        ]
        stage_summary[stage] = {
            "primary_signals": len(stage_items),
            "mature_5d": len(mature_5d),
            "median_5d_close_return_pct": _rounded(median(float(item["close_return_pct"]) for item in mature_5d))
            if mature_5d
            else None,
            "outperformance_rate_pct": _rounded(
                sum(bool(item.get("outperformed")) for item in mature_5d) / len(mature_5d) * 100
            )
            if mature_5d
            else None,
        }
    confidence = "high" if sample_count >= 100 else "medium" if sample_count >= 30 else "low"
    return {
        "total_signals": len(outcomes),
        "primary_signals": len(primary),
        "mature_primary_signals": len(mature_primary_ids),
        "confidence": confidence,
        "horizons": horizon_summary,
        "stages": stage_summary,
    }


def replay_symbol_history(
    item: StockUniverseItem,
    bars: Sequence[DailyBar],
    *,
    repeat_days: int = 3,
    evaluator: CandidateEvaluator = evaluate_candidate,
) -> tuple[list[StrategySignalOutcome], dict[str, int]]:
    ordered_bars = sorted(bars, key=lambda bar: bar.trade_date)
    outcomes: list[StrategySignalOutcome] = []
    stage_counts: defaultdict[str, int] = defaultdict(int)
    evaluated_days = 0
    for signal_index in range(119, len(ordered_bars)):
        history = ordered_bars[: signal_index + 1]
        signal_bar = history[-1]
        float_cap = estimate_float_market_cap_billion(signal_bar)
        candidate = evaluator(
            item,
            history,
            themes=[],
            active_themes=[],
            source_ids=["local_daily_bars"],
            market_profile={"float_market_cap_billion": float_cap or 0},
        )
        evaluated_days += 1
        stage_counts[candidate.stage] += 1
        if candidate.stage not in SIGNAL_STAGES:
            continue
        outcome_values = calculate_horizon_outcomes(ordered_bars, signal_index)
        outcome_id = (
            f"replay-mainboard_volume_price-{candidate.trading_day:%Y%m%d}-"
            f"{candidate.symbol}-{candidate.stage}"
        )
        horizons = outcome_values["horizons"]
        sample_quality = (
            "mature_10d"
            if horizons["10d"]["status"] == "mature"
            else "mature_5d"
            if horizons["5d"]["status"] == "mature"
            else "immature"
        )
        outcomes.append(
            StrategySignalOutcome(
                id=outcome_id,
                origin="replay",
                signal_date=candidate.trading_day,
                symbol=candidate.symbol,
                name=candidate.name,
                stage=candidate.stage,
                total_score=candidate.total_score,
                accumulation_score=candidate.accumulation_score,
                launch_score=candidate.launch_score,
                theme_score=candidate.theme_score,
                risk_penalty=candidate.risk_penalty,
                entry_date=outcome_values["entry_date"],
                entry_price=outcome_values["entry_price"],
                signal_close=signal_bar.close,
                sample_quality=sample_quality,
                metrics={**candidate.metrics, "estimated_float_market_cap_billion": float_cap},
                horizon_outcomes=horizons,
                source_ids=["local_daily_bars"],
                limitations=HISTORICAL_LIMITATIONS,
            )
        )
    outcomes = deduplicate_signals(outcomes, repeat_days=repeat_days, trading_days=[bar.trade_date for bar in ordered_bars])
    return outcomes, {
        "total_symbol_days": len(ordered_bars),
        "evaluated_symbol_days": evaluated_days,
        "raw_signals": len(outcomes),
        "primary_signals": sum(item.included_primary for item in outcomes),
        **{f"stage_{stage}": count for stage, count in stage_counts.items()},
    }


def sync_live_signal_outcomes(trading_day: date) -> StrategyLiveOutcomeSummary:
    existing = {item.id: item for item in list_signal_outcomes(origin="live", limit=10_000)}
    candidates = list_candidates(
        trading_day=trading_day,
        limit=10_000,
        suppress_repeats=True,
        repeat_days=3,
    )
    for candidate in candidates:
        if candidate.stage not in SIGNAL_STAGES:
            continue
        outcome_id = f"live-mainboard_volume_price-{candidate.trading_day:%Y%m%d}-{candidate.symbol}-{candidate.stage}"
        existing[outcome_id] = StrategySignalOutcome(
            id=outcome_id,
            origin="live",
            signal_date=candidate.trading_day,
            symbol=candidate.symbol,
            name=candidate.name,
            stage=candidate.stage,
            total_score=candidate.total_score,
            accumulation_score=candidate.accumulation_score,
            launch_score=candidate.launch_score,
            theme_score=candidate.theme_score,
            risk_penalty=candidate.risk_penalty,
            signal_close=float(candidate.metrics.get("close") or 0) or None,
            metrics=candidate.metrics,
            source_ids=candidate.source_ids,
            limitations=["真实信号结果仅在后续交易日日线写入后更新。"],
        )

    refreshed: list[StrategySignalOutcome] = []
    for outcome in existing.values():
        bars = list_daily_bars(outcome.symbol, limit=5_000)
        signal_index = next((index for index, bar in enumerate(bars) if bar.trade_date == outcome.signal_date), None)
        if signal_index is None:
            limitations = list(dict.fromkeys([*outcome.limitations, "信号日日线缺失"]))
            refreshed.append(outcome.model_copy(update={"limitations": limitations}))
            continue
        calculated = calculate_horizon_outcomes(bars, signal_index)
        horizons = calculated["horizons"]
        sample_quality = (
            "mature_10d"
            if horizons["10d"]["status"] == "mature"
            else "mature_5d"
            if horizons["5d"]["status"] == "mature"
            else "immature"
        )
        refreshed.append(
            outcome.model_copy(
                update={
                    "entry_date": calculated["entry_date"],
                    "entry_price": calculated["entry_price"],
                    "signal_close": bars[signal_index].close,
                    "sample_quality": sample_quality,
                    "horizon_outcomes": horizons,
                }
            )
        )
    if refreshed:
        save_signal_outcomes(refreshed)
    summary = aggregate_signal_outcomes(refreshed)
    return StrategyLiveOutcomeSummary(
        total_signals=len(refreshed),
        mature_signals=int(summary["mature_primary_signals"]),
        summary=summary,
        limitations=["真实信号样本与历史回放分开统计，样本量不足时结论置信度较低。"],
    )


def build_live_outcome_summary() -> StrategyLiveOutcomeSummary:
    outcomes = list_signal_outcomes(origin="live", limit=10_000)
    summary = aggregate_signal_outcomes(outcomes)
    return StrategyLiveOutcomeSummary(
        total_signals=len(outcomes),
        mature_signals=int(summary["mature_primary_signals"]),
        summary=summary,
        limitations=["真实信号样本与历史回放分开统计，样本量不足时结论置信度较低。"],
    )
