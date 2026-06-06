from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def main() -> int:
    from backend.app.database import connect
    from backend.app.market_scope import mainboard_symbol_sql
    from backend.app.models import StrategyBacktestRequest
    from backend.app.repositories import ensure_storage
    from backend.app.strategy_backtest_repository import get_backtest_detail, list_signal_outcomes
    from backend.app.strategy_backtest_tasks import enqueue_strategy_backtest

    ensure_storage()
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT d.symbol, COUNT(*) AS bars, MAX(d.trade_date) AS latest_date
            FROM daily_bars d
            LEFT JOIN stock_universe u ON u.symbol = d.symbol
            WHERE d.adjust = 'qfq'
              AND {mainboard_symbol_sql('d.symbol')}
              AND u.symbol IS NOT NULL
              AND COALESCE(u.is_st, FALSE) = FALSE
              AND UPPER(COALESCE(u.name, d.symbol)) NOT LIKE '%%ST%%'
              AND COALESCE(u.name, d.symbol) NOT LIKE '%%退%%'
            GROUP BY d.symbol
            HAVING COUNT(*) >= 120
            ORDER BY latest_date DESC, bars DESC
            LIMIT 3
            """
        ).fetchall()
    symbols = [row["symbol"] for row in rows]
    request = StrategyBacktestRequest(symbols=symbols, repeat_days=3)
    run = enqueue_strategy_backtest(request)

    deadline = time.monotonic() + 180
    detail = None
    while time.monotonic() < deadline:
        detail = get_backtest_detail(run.id)
        if detail and detail.run.status in {"completed", "failed"}:
            break
        time.sleep(1)

    signals = list_signal_outcomes(backtest_run_id=run.id, origin="replay", primary_only=True, limit=5)
    payload = {
        "requested_symbols": symbols,
        "run": _jsonable(detail.run if detail else run),
        "funnel": _jsonable(detail.funnel if detail else None),
        "sample_signals": [_jsonable(item) for item in signals],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))

    if detail is None or detail.run.status != "completed":
        return 1
    if detail.funnel is None:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
