from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


FreshnessStatus = Literal["fresh", "stale", "missing"]


class DataFreshnessInputs(BaseModel):
    snapshot_date: date | None = None
    daily_bar_date: date | None = None
    announcement_coverage_date: date | None = None
    report_date: date | None = None
    agent_report_date: date | None = None


class FreshnessCheck(BaseModel):
    scope: str
    status: FreshnessStatus
    expected_date: date
    actual_date: date | None = None
    message: str


class DataFreshnessResult(BaseModel):
    status: FreshnessStatus
    checks: list[FreshnessCheck] = Field(default_factory=list)


def evaluate_data_freshness(target_date: date, inputs: DataFreshnessInputs) -> DataFreshnessResult:
    checks = [
        _check("market_snapshot", target_date, inputs.snapshot_date, "Market snapshot"),
        _check("daily_bars", target_date, inputs.daily_bar_date, "Daily bars"),
        _check("announcements", target_date, inputs.announcement_coverage_date, "Announcement coverage"),
        _check("daily_report", target_date, inputs.report_date, "Deterministic daily report"),
        _check("agent_brief", target_date, inputs.agent_report_date, "Agent post-market brief"),
    ]
    statuses = {check.status for check in checks}
    overall: FreshnessStatus = "missing" if "missing" in statuses else "stale" if "stale" in statuses else "fresh"
    return DataFreshnessResult(status=overall, checks=checks)


def _check(scope: str, expected: date, actual: date | None, label: str) -> FreshnessCheck:
    if actual is None:
        return FreshnessCheck(
            scope=scope,
            status="missing",
            expected_date=expected,
            message=f"{label} is missing for {expected.isoformat()}.",
        )
    if actual != expected:
        return FreshnessCheck(
            scope=scope,
            status="stale",
            expected_date=expected,
            actual_date=actual,
            message=f"{label} latest date is {actual.isoformat()}, expected {expected.isoformat()}.",
        )
    return FreshnessCheck(
        scope=scope,
        status="fresh",
        expected_date=expected,
        actual_date=actual,
        message=f"{label} covers {expected.isoformat()}.",
    )
