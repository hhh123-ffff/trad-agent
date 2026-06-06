from __future__ import annotations

from typing import Any

from .stealth_repository import build_data_quality_summary, list_candidates, list_observations
from .tracking_service import build_information_summary, tracking_daily_report


def build_post_market_agent_context() -> dict[str, Any]:
    report = _dump(tracking_daily_report())
    information = _dump(build_information_summary())
    candidates = [_candidate_view(_dump(item)) for item in list_candidates(min_score=35, limit=12, suppress_repeats=True)[:12]]
    observations = [_observation_view(_dump(item)) for item in list_observations()[:30]]
    quality = _quality_view(_dump(build_data_quality_summary()))
    information_view = _information_view(information)
    report_view = _report_view(report)
    source_ids = sorted(
        {
            *_strings(report_view.get("source_ids")),
            *_strings(information_view.get("source_ids")),
            *(source_id for candidate in candidates for source_id in _strings(candidate.get("source_ids"))),
        }
    )
    return {
        "trading_day": str(report_view.get("trading_day") or ""),
        "data_quality": quality,
        "information": information_view,
        "candidates": candidates,
        "observations": observations,
        "report": report_view,
        "source_ids": source_ids,
    }


def _report_view(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "trading_day": report.get("trading_day"),
        "headline": report.get("headline", ""),
        "summary": report.get("summary", ""),
        "sections": [
            {
                "title": section.get("title", ""),
                "summary": section.get("summary", ""),
                "evidence": _strings(section.get("evidence"))[:8],
                "metrics": section.get("metrics", {}) if isinstance(section.get("metrics"), dict) else {},
                "warnings": _strings(section.get("warnings"))[:8],
            }
            for section in report.get("sections", [])[:8]
            if isinstance(section, dict)
        ],
        "source_ids": _strings(report.get("source_ids")),
    }


def _information_view(information: dict[str, Any]) -> dict[str, Any]:
    return {
        "announcement_count": int(information.get("announcement_count") or 0),
        "news_count": int(information.get("news_count") or 0),
        "by_importance": information.get("by_importance", {}) if isinstance(information.get("by_importance"), dict) else {},
        "by_symbol": [
            {
                "symbol": item.get("symbol"),
                "total": item.get("total", 0),
                "news": item.get("news", 0),
                "announcements": item.get("announcements", 0),
                "high_importance": item.get("high_importance", 0),
                "latest_title": item.get("latest_title", ""),
            }
            for item in information.get("by_symbol", [])[:12]
            if isinstance(item, dict)
        ],
        "latest_items": [
            {
                "id": item.get("id"),
                "symbol": item.get("symbol"),
                "title": item.get("title", ""),
                "event_type": item.get("event_type", ""),
                "importance": item.get("importance", "medium"),
                "source_id": item.get("source_id", ""),
            }
            for item in information.get("latest_items", [])[:12]
            if isinstance(item, dict)
        ],
        "warnings": _strings(information.get("warnings"))[:8],
        "source_ids": _strings(information.get("source_ids")),
    }


def _candidate_view(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        key: candidate.get(key)
        for key in [
            "symbol",
            "name",
            "stage",
            "total_score",
            "accumulation_score",
            "launch_score",
            "theme_score",
            "risk_penalty",
            "evidence",
            "risks",
            "metrics",
            "themes",
            "source_ids",
        ]
    }


def _observation_view(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        key: observation.get(key)
        for key in ["symbol", "status", "reason", "invalidation_rule", "next_focus", "days_observed"]
    }


def _quality_view(quality: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    if not quality.get("latest_trade_date"):
        warnings.append("Latest daily-bar trading date is missing.")
    if int(quality.get("stale_symbols") or 0) > 0:
        warnings.append("Some symbols have stale daily bars.")
    if int(quality.get("zero_amount_symbols") or 0) > 0:
        warnings.append("Some latest daily bars have zero amount.")
    return {
        key: quality.get(key)
        for key in [
            "latest_trade_date",
            "universe_symbols",
            "latest_bar_symbols",
            "stale_symbols",
            "zero_amount_symbols",
            "short_history_symbols",
            "checked_at",
        ]
    } | {"warnings": warnings}


def _dump(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    raise TypeError(f"Expected a structured model, got {type(value).__name__}.")


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item) for item in value if str(item).strip()})
