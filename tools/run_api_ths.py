from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]

THS_API_DEFAULTS = {
    "MARKETLENS_MARKET_PROVIDER": "ths",
    "MARKETLENS_HISTORY_PROVIDER": "ths_delayed",
    "MARKETLENS_INFO_PROVIDER": "ths",
    "MARKETLENS_ENABLE_SCHEDULER": "0",
    "THS_HISTORY_FALLBACK_TO_AKSHARE": "0",
    "THS_THEME_FALLBACK_TO_AKSHARE": "0",
}


def main() -> int:
    for key, value in THS_API_DEFAULTS.items():
        os.environ.setdefault(key, value)

    host = os.environ.get("MARKETLENS_API_HOST", "127.0.0.1")
    port = os.environ.get("MARKETLENS_API_PORT", "8000")
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.app.main:app",
        "--host",
        host,
        "--port",
        port,
    ]
    if os.environ.get("MARKETLENS_API_RELOAD", "0").strip() == "1":
        command.append("--reload")

    print(
        "Starting MarketLens API in Tonghuashun mode "
        f"(market={os.environ['MARKETLENS_MARKET_PROVIDER']}, "
        f"history={os.environ['MARKETLENS_HISTORY_PROVIDER']}, "
        f"info={os.environ['MARKETLENS_INFO_PROVIDER']}, "
        f"history_fallback={os.environ['THS_HISTORY_FALLBACK_TO_AKSHARE']}, "
        f"theme_fallback={os.environ['THS_THEME_FALLBACK_TO_AKSHARE']})"
    )
    return subprocess.call(command, cwd=ROOT_DIR)


if __name__ == "__main__":
    raise SystemExit(main())
