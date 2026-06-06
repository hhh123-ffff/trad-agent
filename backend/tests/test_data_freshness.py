from datetime import date

from backend.app.data_freshness import DataFreshnessInputs, evaluate_data_freshness


TARGET = date(2026, 6, 5)


def test_data_freshness_is_fresh_when_all_scopes_match_target_date():
    result = evaluate_data_freshness(
        TARGET,
        DataFreshnessInputs(
            snapshot_date=TARGET,
            daily_bar_date=TARGET,
            announcement_coverage_date=TARGET,
            report_date=TARGET,
            agent_report_date=TARGET,
        ),
    )

    assert result.status == "fresh"
    assert {check.scope: check.status for check in result.checks} == {
        "market_snapshot": "fresh",
        "daily_bars": "fresh",
        "announcements": "fresh",
        "daily_report": "fresh",
        "agent_brief": "fresh",
    }


def test_data_freshness_distinguishes_stale_and_missing_scopes():
    result = evaluate_data_freshness(
        TARGET,
        DataFreshnessInputs(
            snapshot_date=date(2026, 6, 4),
            daily_bar_date=None,
            announcement_coverage_date=TARGET,
            report_date=TARGET,
            agent_report_date=date(2026, 6, 4),
        ),
    )
    checks = {check.scope: check for check in result.checks}

    assert result.status == "missing"
    assert checks["market_snapshot"].status == "stale"
    assert checks["daily_bars"].status == "missing"
    assert checks["daily_bars"].actual_date is None
    assert checks["agent_brief"].status == "stale"
    assert all(check.message for check in result.checks)
