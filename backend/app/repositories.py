from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from .database import connect, get_redis, init_schema
from .market_provider import live_source, sina_source
from .models import (
    AssistantAnswer,
    SourceRef,
    WatchlistItemCreate,
    WatchlistItemUpdate,
    WatchlistStock,
)
from .ths_provider import ths_market_source

DEFAULT_USER_ID = "local-user"
LIVE_SOURCE_IDS = ("src-eastmoney-live", "src-sina-live", "src-ths-quantapi-market")
_initialized = False


def _json(value: Any) -> Jsonb:
    return Jsonb(value)


def _as_float(value: Any) -> float:
    return float(value or 0)


def _source_from_row(row: dict[str, Any]) -> SourceRef:
    return SourceRef(
        id=row["id"],
        name=row["name"],
        url=row["url"],
        as_of=row["as_of"],
        license=row["license"],
        freshness=row["freshness"],
    )


def _watchlist_from_row(row: dict[str, Any]) -> WatchlistStock:
    return WatchlistStock(
        symbol=row["symbol"],
        name=row["name"],
        group=row["group_name"],
        price=_as_float(row["price"]),
        change_pct=_as_float(row["change_pct"]),
        volume_ratio=_as_float(row["volume_ratio"]),
        tags=row["tags"] or [],
        attention_reason=row["attention_reason"],
        latest_event=row["latest_event"],
        risk_flags=row["risk_flags"] or [],
        source_id=row["source_id"],
    )


def ensure_storage() -> None:
    global _initialized
    if _initialized:
        return
    init_schema()
    ensure_live_source()
    _initialized = True


def ensure_live_source() -> None:
    sources = [live_source(), sina_source(), ths_market_source()]
    with connect() as conn:
        for source in sources:
            conn.execute(
                """
                INSERT INTO data_sources (id, name, url, as_of, license, freshness)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    url = EXCLUDED.url,
                    as_of = EXCLUDED.as_of,
                    license = EXCLUDED.license,
                    freshness = EXCLUDED.freshness,
                    updated_at = NOW()
                """,
                (source.id, source.name, source.url, source.as_of, source.license, source.freshness),
            )


def list_sources() -> list[SourceRef]:
    ensure_storage()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM data_sources WHERE id = ANY(%s) ORDER BY id", (list(LIVE_SOURCE_IDS),)).fetchall()
    return [_source_from_row(row) for row in rows]


def list_watchlist(user_id: str = DEFAULT_USER_ID) -> list[WatchlistStock]:
    ensure_storage()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM watchlist_items
            WHERE user_id = %s AND source_id = ANY(%s)
            ORDER BY updated_at DESC, symbol ASC
            """,
            (user_id, list(LIVE_SOURCE_IDS)),
        ).fetchall()
    return [_watchlist_from_row(row) for row in rows]


def get_watchlist_item(symbol: str, user_id: str = DEFAULT_USER_ID) -> WatchlistStock | None:
    ensure_storage()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM watchlist_items WHERE user_id = %s AND symbol = %s AND source_id = ANY(%s)",
            (user_id, symbol.upper(), list(LIVE_SOURCE_IDS)),
        ).fetchone()
    return _watchlist_from_row(row) if row else None


def upsert_watchlist_item(payload: WatchlistItemCreate, user_id: str = DEFAULT_USER_ID) -> WatchlistStock:
    ensure_storage()
    symbol = payload.symbol.upper()
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO watchlist_items (
                user_id, symbol, name, group_name, price, change_pct, volume_ratio,
                tags, attention_reason, latest_event, risk_flags, source_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, symbol) DO UPDATE SET
                name = EXCLUDED.name,
                group_name = EXCLUDED.group_name,
                price = EXCLUDED.price,
                change_pct = EXCLUDED.change_pct,
                volume_ratio = EXCLUDED.volume_ratio,
                tags = EXCLUDED.tags,
                attention_reason = EXCLUDED.attention_reason,
                latest_event = EXCLUDED.latest_event,
                risk_flags = EXCLUDED.risk_flags,
                source_id = EXCLUDED.source_id,
                updated_at = NOW()
            RETURNING *
            """,
            (
                user_id,
                symbol,
                payload.name,
                payload.group,
                payload.price,
                payload.change_pct,
                payload.volume_ratio,
                _json(payload.tags),
                payload.attention_reason,
                payload.latest_event,
                _json(payload.risk_flags),
                payload.source_id,
            ),
        ).fetchone()
        _cache_watchlist_count(conn, user_id)
    return _watchlist_from_row(row)


def update_watchlist_item(symbol: str, payload: WatchlistItemUpdate, user_id: str = DEFAULT_USER_ID) -> WatchlistStock:
    ensure_storage()
    current = get_watchlist_item(symbol, user_id=user_id)
    if current is None:
        raise KeyError(symbol)
    merged = WatchlistItemCreate(
        symbol=current.symbol,
        name=payload.name if payload.name is not None else current.name,
        group=payload.group if payload.group is not None else current.group,
        price=payload.price if payload.price is not None else current.price,
        change_pct=payload.change_pct if payload.change_pct is not None else current.change_pct,
        volume_ratio=payload.volume_ratio if payload.volume_ratio is not None else current.volume_ratio,
        tags=payload.tags if payload.tags is not None else current.tags,
        attention_reason=payload.attention_reason if payload.attention_reason is not None else current.attention_reason,
        latest_event=payload.latest_event if payload.latest_event is not None else current.latest_event,
        risk_flags=payload.risk_flags if payload.risk_flags is not None else current.risk_flags,
        source_id=payload.source_id if payload.source_id is not None else current.source_id,
    )
    return upsert_watchlist_item(merged, user_id=user_id)


def delete_watchlist_item(symbol: str, user_id: str = DEFAULT_USER_ID) -> bool:
    ensure_storage()
    with connect() as conn:
        cursor = conn.execute(
            "DELETE FROM watchlist_items WHERE user_id = %s AND symbol = %s AND source_id = ANY(%s)",
            (user_id, symbol.upper(), list(LIVE_SOURCE_IDS)),
        )
        _cache_watchlist_count(conn, user_id)
    return bool(cursor.rowcount)


def _cache_watchlist_count(conn: Any, user_id: str) -> None:
    count = conn.execute(
        "SELECT COUNT(*) AS count FROM watchlist_items WHERE user_id = %s AND source_id = ANY(%s)",
        (user_id, list(LIVE_SOURCE_IDS)),
    ).fetchone()["count"]
    try:
        get_redis().set(f"watchlist:{user_id}:live_count", str(count), ex=300)
    except Exception:
        pass


def save_assistant_query(payload_query: str, answer: AssistantAnswer, user_id: str = DEFAULT_USER_ID) -> int:
    ensure_storage()
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO assistant_queries (
                user_id, query, answer, confidence, blocked_by_compliance,
                evidence, citation_ids, missing_information
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                user_id,
                payload_query,
                answer.answer,
                answer.confidence.value,
                answer.blocked_by_compliance,
                _json(answer.evidence),
                _json([source.id for source in answer.citations]),
                _json(answer.missing_information),
            ),
        ).fetchone()
    return int(row["id"])


def list_assistant_queries(limit: int = 50, user_id: str = DEFAULT_USER_ID) -> list[dict[str, Any]]:
    ensure_storage()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, query, answer, confidence, blocked_by_compliance,
                   evidence, citation_ids, missing_information, created_at
            FROM assistant_queries
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def watchlist_count_cache(user_id: str = DEFAULT_USER_ID) -> str | None:
    try:
        return get_redis().get(f"watchlist:{user_id}:live_count")
    except Exception:
        return None
