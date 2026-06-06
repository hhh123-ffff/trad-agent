from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from .models import StrategyBacktestRequest, StrategyBacktestRun
from .strategy_backtest import HISTORICAL_LIMITATIONS, aggregate_signal_outcomes, replay_symbol_history
from .strategy_backtest_repository import (
    create_backtest_run,
    load_backtest_dataset,
    save_backtest_funnel,
    save_signal_outcomes,
    update_backtest_run,
)


_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="strategy-backtest")
_submit_lock = Lock()


def enqueue_strategy_backtest(request: StrategyBacktestRequest) -> StrategyBacktestRun:
    run = create_backtest_run(request)
    with _submit_lock:
        _executor.submit(run_strategy_backtest_task, run.id, request)
    return run


def run_strategy_backtest_task(run_id: str, request: StrategyBacktestRequest) -> None:
    update_backtest_run(
        run_id,
        status="running",
        progress=0,
        error=None,
        message="正在读取本地日线并执行历史回放。",
        started=True,
    )
    try:
        dataset = load_backtest_dataset(request)
        total_symbols = len(dataset)
        all_outcomes = []
        funnel = Counter()
        failures: list[dict[str, str]] = []
        for index, (item, bars) in enumerate(dataset, start=1):
            funnel["available_symbols"] += 1
            funnel["available_symbol_days"] += len(bars)
            try:
                outcomes, symbol_funnel = replay_symbol_history(item, bars, repeat_days=request.repeat_days)
                if request.start_date:
                    outcomes = [outcome for outcome in outcomes if outcome.signal_date >= request.start_date]
                persisted = [
                    outcome.model_copy(
                        update={
                            "id": f"{run_id}-{outcome.id}",
                            "backtest_run_id": run_id,
                            "origin": "replay",
                        }
                    )
                    for outcome in outcomes
                ]
                save_signal_outcomes(persisted)
                all_outcomes.extend(persisted)
                funnel.update(symbol_funnel)
            except Exception as exc:
                failures.append({"symbol": item.symbol, "error": str(exc)})
                funnel["failed_symbols"] += 1
            progress = index / total_symbols if total_symbols else 1
            update_backtest_run(
                run_id,
                total_symbols=total_symbols,
                evaluated_symbol_days=int(funnel["evaluated_symbol_days"]),
                raw_signals=len(all_outcomes),
                primary_signals=sum(outcome.included_primary for outcome in all_outcomes),
                progress=progress,
                message=f"历史回放进行中：{index}/{total_symbols} 只股票。",
            )

        summary = aggregate_signal_outcomes(all_outcomes)
        save_backtest_funnel(run_id, {key: int(value) for key, value in funnel.items()})
        update_backtest_run(
            run_id,
            status="completed",
            total_symbols=total_symbols,
            total_symbol_days=int(funnel["available_symbol_days"]),
            evaluated_symbol_days=int(funnel["evaluated_symbol_days"]),
            raw_signals=len(all_outcomes),
            primary_signals=sum(outcome.included_primary for outcome in all_outcomes),
            mature_signals=int(summary["mature_primary_signals"]),
            progress=1,
            summary=summary,
            data_quality={
                "available_symbols": total_symbols,
                "failed_symbols": len(failures),
                "failures": failures[:50],
            },
            limitations=HISTORICAL_LIMITATIONS,
            message=f"历史回放完成，共形成 {summary['primary_signals']} 个主样本。",
            error=None,
            finished=True,
        )
    except Exception as exc:
        update_backtest_run(
            run_id,
            status="failed",
            error=str(exc),
            message="历史回放任务失败，已保留错误原因。",
            finished=True,
        )
