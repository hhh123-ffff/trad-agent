from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

THS_SMOKE_DEFAULTS = {
    "MARKETLENS_MARKET_PROVIDER": "ths",
    "MARKETLENS_HISTORY_PROVIDER": "ths_delayed",
    "MARKETLENS_INFO_PROVIDER": "ths",
    "MARKETLENS_ENABLE_SCHEDULER": "0",
    "MARKETLENS_POST_MARKET_ENABLE_SCAN": "0",
    "THS_HISTORY_FALLBACK_TO_AKSHARE": "0",
    "THS_THEME_FALLBACK_TO_AKSHARE": "0",
}


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Tonghuashun-mode post-market replay smoke test.")
    parser.add_argument("--scan", action="store_true", help="Enable the bounded stealth scan during the smoke run.")
    args = parser.parse_args()

    for key, value in THS_SMOKE_DEFAULTS.items():
        os.environ.setdefault(key, value)
    if args.scan:
        os.environ["MARKETLENS_POST_MARKET_ENABLE_SCAN"] = "1"

    from backend.app.repositories import ensure_storage
    from backend.app.tracking_service import run_tracking_job, tracking_daily_report

    ensure_storage()
    run = run_tracking_job("post_market_replay")
    report = tracking_daily_report()
    payload = {
        "run": _jsonable(run),
        "report": {
            "trading_day": report.trading_day.isoformat(),
            "headline": report.headline,
            "section_count": len(report.sections),
            "source_ids": report.source_ids,
        },
        "env": {
            "market_provider": os.environ["MARKETLENS_MARKET_PROVIDER"],
            "history_provider": os.environ["MARKETLENS_HISTORY_PROVIDER"],
            "info_provider": os.environ["MARKETLENS_INFO_PROVIDER"],
            "post_market_scan": os.environ["MARKETLENS_POST_MARKET_ENABLE_SCAN"],
            "history_fallback": os.environ["THS_HISTORY_FALLBACK_TO_AKSHARE"],
            "theme_fallback": os.environ["THS_THEME_FALLBACK_TO_AKSHARE"],
            "ths_token_configured": bool(os.environ.get("THS_ACCESS_TOKEN") or os.environ.get("THS_REFRESH_TOKEN")),
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0 if run.status == "completed" and len(report.sections) == 6 and report.source_ids else 1


if __name__ == "__main__":
    raise SystemExit(main())
