from __future__ import annotations

import os

from .tracking_service import run_tracking_job

_scheduler = None


def start_scheduler() -> None:
    global _scheduler
    if os.getenv("MARKETLENS_ENABLE_SCHEDULER", "0") != "1" or _scheduler is not None:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except Exception:
        return

    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(lambda: run_tracking_job("preopen_prepare"), CronTrigger(hour=7, minute=30), id="preopen_prepare", replace_existing=True)
    scheduler.add_job(lambda: run_tracking_job("preopen_refresh"), CronTrigger(hour=9, minute=20), id="preopen_refresh", replace_existing=True)
    scheduler.add_job(lambda: run_tracking_job("intraday_snapshot"), CronTrigger(day_of_week="mon-fri", hour="9-11,13-14", minute="*/5"), id="intraday_snapshot", replace_existing=True)
    scheduler.add_job(lambda: run_tracking_job("midday_summary"), CronTrigger(hour=11, minute=35), id="midday_summary", replace_existing=True)
    scheduler.add_job(lambda: run_tracking_job("close_snapshot"), CronTrigger(hour=15, minute=5), id="close_snapshot", replace_existing=True)
    scheduler.add_job(lambda: run_tracking_job("news_explain"), CronTrigger(hour=16, minute=30), id="news_explain", replace_existing=True)
    scheduler.add_job(lambda: run_tracking_job("post_market_replay"), CronTrigger(day_of_week="mon-fri", hour=20, minute=10), id="post_market_replay", replace_existing=True)
    scheduler.add_job(lambda: run_tracking_job("daily_report"), CronTrigger(hour=20, minute=30), id="daily_report", replace_existing=True)
    scheduler.start()
    _scheduler = scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    finally:
        _scheduler = None
