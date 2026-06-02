from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from .database import connect
from .models import (
    AnnouncementItem,
    DailyTrackingReport,
    JobRun,
    MarketEvent,
    MarketIndex,
    MarketSnapshot,
    MarketTemperature,
    NewsItem,
    SectorSnapshot,
    WatchlistStock,
)


def _json(value: Any) -> Jsonb:
    return Jsonb(value)


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _day_window(trading_day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(trading_day, time.min)
    return start, start + timedelta(days=1)


def create_job_run(job_name: str, status: str = "running", message: str = "", affected_scope: dict[str, Any] | None = None) -> JobRun:
    run_id = uuid4().hex
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO job_runs (id, job_name, status, message, affected_scope)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (run_id, job_name, status, message, _json(affected_scope or {})),
        ).fetchone()
    return _job_run_from_row(row)


def finish_job_run(run_id: str, status: str, message: str = "", error: str | None = None, affected_scope: dict[str, Any] | None = None) -> JobRun:
    with connect() as conn:
        row = conn.execute(
            """
            UPDATE job_runs
            SET status = %s,
                message = %s,
                error = %s,
                affected_scope = COALESCE(%s, affected_scope),
                finished_at = NOW(),
                duration_ms = GREATEST(EXTRACT(EPOCH FROM (NOW() - started_at))::INTEGER * 1000, 0),
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (status, message, error, _json(affected_scope) if affected_scope is not None else None, run_id),
        ).fetchone()
    return _job_run_from_row(row)


def list_job_runs(limit: int = 40, job_name: str | None = None) -> list[JobRun]:
    params: list[Any] = []
    where = ""
    if job_name:
        where = "WHERE job_name = %s"
        params.append(job_name)
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM job_runs
            {where}
            ORDER BY started_at DESC
            LIMIT %s
            """,
            tuple(params),
        ).fetchall()
    return [_job_run_from_row(row) for row in rows]


def save_market_events(events: list[MarketEvent]) -> None:
    if not events:
        return
    with connect() as conn:
        for event in events:
            conn.execute(
                """
                INSERT INTO market_events (
                    id, occurred_at, type, title, summary, affected_symbols, affected_sectors,
                    importance, fact_basis, inference, confidence, source_ids, compliance_label
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    occurred_at = EXCLUDED.occurred_at,
                    type = EXCLUDED.type,
                    title = EXCLUDED.title,
                    summary = EXCLUDED.summary,
                    affected_symbols = EXCLUDED.affected_symbols,
                    affected_sectors = EXCLUDED.affected_sectors,
                    importance = EXCLUDED.importance,
                    fact_basis = EXCLUDED.fact_basis,
                    inference = EXCLUDED.inference,
                    confidence = EXCLUDED.confidence,
                    source_ids = EXCLUDED.source_ids,
                    compliance_label = EXCLUDED.compliance_label,
                    updated_at = NOW()
                """,
                (
                    event.id,
                    event.occurred_at,
                    event.type.value if hasattr(event.type, "value") else event.type,
                    event.title,
                    event.summary,
                    _json(event.affected_symbols),
                    _json(event.affected_sectors),
                    event.importance,
                    _json(event.fact_basis),
                    event.inference,
                    event.confidence.value if hasattr(event.confidence, "value") else event.confidence,
                    _json(event.source_ids),
                    event.compliance_label,
                ),
            )


def save_market_snapshot(
    *,
    captured_at: datetime,
    interval: str,
    provider: str,
    source_id: str,
    license_note: str,
    temperature: MarketTemperature,
    indexes: list[MarketIndex],
    sectors: list[SectorSnapshot],
    watchlist: list[WatchlistStock],
    events: list[MarketEvent],
) -> MarketSnapshot:
    snapshot_id = f"{captured_at:%Y%m%d%H%M}-{interval}"
    save_market_events(events)
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO market_snapshots (
                id, captured_at, interval, provider, source_id, license_note,
                market_temperature, indexes, sectors, watchlist, event_ids
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                captured_at = EXCLUDED.captured_at,
                interval = EXCLUDED.interval,
                provider = EXCLUDED.provider,
                source_id = EXCLUDED.source_id,
                license_note = EXCLUDED.license_note,
                market_temperature = EXCLUDED.market_temperature,
                indexes = EXCLUDED.indexes,
                sectors = EXCLUDED.sectors,
                watchlist = EXCLUDED.watchlist,
                event_ids = EXCLUDED.event_ids
            RETURNING *
            """,
            (
                snapshot_id,
                captured_at,
                interval,
                provider,
                source_id,
                license_note,
                _json(_dump(temperature)),
                _json([_dump(item) for item in indexes]),
                _json([_dump(item) for item in sectors]),
                _json([_dump(item) for item in watchlist]),
                _json([event.id for event in events]),
            ),
        ).fetchone()
    return _snapshot_from_row(row)


def list_market_snapshots(trading_day: date, interval: str = "5m") -> list[MarketSnapshot]:
    start, end = _day_window(trading_day)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM market_snapshots
            WHERE captured_at >= %s AND captured_at < %s AND interval = %s
            ORDER BY captured_at ASC
            """,
            (start, end, interval),
        ).fetchall()
    return [_snapshot_from_row(row) for row in rows]


def list_market_events(trading_day: date, symbol: str | None = None, event_type: str | None = None) -> list[MarketEvent]:
    start, end = _day_window(trading_day)
    params: list[Any] = [start, end]
    where = "occurred_at >= %s AND occurred_at < %s"
    if event_type:
        where += " AND type = %s"
        params.append(event_type)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM market_events
            WHERE {where}
            ORDER BY occurred_at ASC
            """,
            tuple(params),
        ).fetchall()
    events = [_event_from_row(row) for row in rows]
    if symbol:
        normalized = symbol.upper()
        events = [event for event in events if normalized in event.affected_symbols]
    return events


def save_news_items(items: list[NewsItem]) -> None:
    _save_content_items("news_items", items)


def save_announcement_items(items: list[AnnouncementItem]) -> None:
    _save_content_items("announcement_items", items)


def list_news_items(trading_day: date, symbol: str | None = None) -> list[NewsItem]:
    rows = _list_content_rows("news_items", trading_day, symbol)
    return [_news_from_row(row) for row in rows]


def list_announcement_items(trading_day: date, symbol: str | None = None) -> list[AnnouncementItem]:
    rows = _list_content_rows("announcement_items", trading_day, symbol)
    return [_announcement_from_row(row) for row in rows]


def save_daily_tracking_report(report: DailyTrackingReport) -> DailyTrackingReport:
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO daily_tracking_reports (trading_day, generated_at, headline, summary, sections, source_ids)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (trading_day) DO UPDATE SET
                generated_at = EXCLUDED.generated_at,
                headline = EXCLUDED.headline,
                summary = EXCLUDED.summary,
                sections = EXCLUDED.sections,
                source_ids = EXCLUDED.source_ids,
                updated_at = NOW()
            RETURNING *
            """,
            (
                report.trading_day,
                report.generated_at,
                report.headline,
                report.summary,
                _json(report.sections),
                _json(report.source_ids),
            ),
        ).fetchone()
    return report.model_copy(
        update={
            "generated_at": row["generated_at"],
            "headline": row["headline"],
            "summary": row["summary"],
            "sections": row["sections"] or [],
            "source_ids": row["source_ids"] or [],
        }
    )


def get_daily_tracking_report(trading_day: date) -> DailyTrackingReport | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM daily_tracking_reports WHERE trading_day = %s", (trading_day,)).fetchone()
    if not row:
        return None
    return DailyTrackingReport(
        trading_day=row["trading_day"],
        generated_at=row["generated_at"],
        headline=row["headline"],
        summary=row["summary"],
        sections=row["sections"] or [],
        source_ids=row["source_ids"] or [],
    )


def _save_content_items(table: str, items: list[NewsItem] | list[AnnouncementItem]) -> None:
    if not items:
        return
    with connect() as conn:
        for item in items:
            conn.execute(
                f"""
                INSERT INTO {table} (
                    id, symbol, title, summary, published_at, source_url, source_name,
                    event_type, importance, provider, source_id, license_note
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    symbol = EXCLUDED.symbol,
                    title = EXCLUDED.title,
                    summary = EXCLUDED.summary,
                    published_at = EXCLUDED.published_at,
                    source_url = EXCLUDED.source_url,
                    source_name = EXCLUDED.source_name,
                    event_type = EXCLUDED.event_type,
                    importance = EXCLUDED.importance,
                    provider = EXCLUDED.provider,
                    source_id = EXCLUDED.source_id,
                    license_note = EXCLUDED.license_note,
                    updated_at = NOW()
                """,
                (
                    item.id,
                    item.symbol,
                    item.title,
                    item.summary,
                    item.published_at,
                    item.source_url,
                    item.source_name,
                    item.event_type,
                    item.importance,
                    item.provider,
                    item.source_id,
                    item.license_note,
                ),
            )


def _list_content_rows(table: str, trading_day: date, symbol: str | None = None) -> list[dict[str, Any]]:
    start, end = _day_window(trading_day)
    params: list[Any] = [start, end]
    where = "published_at >= %s AND published_at < %s"
    if symbol:
        where += " AND symbol = %s"
        params.append(symbol.upper())
    with connect() as conn:
        return conn.execute(
            f"""
            SELECT *
            FROM {table}
            WHERE {where}
            ORDER BY published_at DESC
            """,
            tuple(params),
        ).fetchall()


def _job_run_from_row(row: dict[str, Any]) -> JobRun:
    return JobRun(
        id=row["id"],
        job_name=row["job_name"],
        status=row["status"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        duration_ms=int(row["duration_ms"] or 0),
        affected_scope=row["affected_scope"] or {},
        message=row["message"] or "",
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _snapshot_from_row(row: dict[str, Any]) -> MarketSnapshot:
    return MarketSnapshot(
        id=row["id"],
        captured_at=row["captured_at"],
        interval=row["interval"],
        provider=row["provider"],
        source_id=row["source_id"],
        license_note=row["license_note"],
        market_temperature=MarketTemperature(**(row["market_temperature"] or {})),
        indexes=[MarketIndex(**item) for item in row["indexes"] or []],
        sectors=[SectorSnapshot(**item) for item in row["sectors"] or []],
        watchlist=[WatchlistStock(**item) for item in row["watchlist"] or []],
        event_ids=row["event_ids"] or [],
    )


def _event_from_row(row: dict[str, Any]) -> MarketEvent:
    return MarketEvent(
        id=row["id"],
        occurred_at=row["occurred_at"],
        type=row["type"],
        title=row["title"],
        summary=row["summary"],
        affected_symbols=row["affected_symbols"] or [],
        affected_sectors=row["affected_sectors"] or [],
        importance=row["importance"],
        fact_basis=row["fact_basis"] or [],
        inference=row["inference"],
        confidence=row["confidence"],
        source_ids=row["source_ids"] or [],
        compliance_label=row["compliance_label"],
    )


def _news_from_row(row: dict[str, Any]) -> NewsItem:
    return NewsItem(
        id=row["id"],
        symbol=row["symbol"],
        title=row["title"],
        summary=row["summary"],
        published_at=row["published_at"],
        source_url=row["source_url"],
        source_name=row["source_name"],
        event_type=row["event_type"],
        importance=row["importance"],
        provider=row["provider"],
        source_id=row["source_id"],
        license_note=row["license_note"],
    )


def _announcement_from_row(row: dict[str, Any]) -> AnnouncementItem:
    return AnnouncementItem(
        id=row["id"],
        symbol=row["symbol"],
        title=row["title"],
        summary=row["summary"],
        published_at=row["published_at"],
        source_url=row["source_url"],
        source_name=row["source_name"],
        event_type=row["event_type"],
        importance=row["importance"],
        provider=row["provider"],
        source_id=row["source_id"],
        license_note=row["license_note"],
    )
