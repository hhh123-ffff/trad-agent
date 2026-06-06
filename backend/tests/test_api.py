from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app import main as main_module
from backend.app import repositories
from backend.app import tracking_service
from backend.app.database import connect
from backend.app.main import app
from backend.app.market_provider import live_source
from backend.app.models import (
    Confidence,
    DailyBar,
    EventType,
    MarketEvent,
    MarketIndex,
    MarketTemperature,
    NewsItem,
    AnnouncementItem,
    ProviderMeta,
    SectorSnapshot,
    StealthScanTask,
    StockUniverseItem,
    ThemeMembership,
    WatchlistItemCreate,
)
from backend.app.stealth_repository import create_scan_task, list_candidates, record_scan_failure, save_daily_bars, save_scan_results
from backend.app.stealth_scanner import evaluate_candidate
from backend.app.tracking_repository import _day_window


def _delete_stealth_test_symbol(symbol: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM observation_journal WHERE symbol = %s", (symbol,))
        conn.execute("DELETE FROM observation_list WHERE symbol = %s", (symbol,))
        conn.execute("DELETE FROM stealth_scan_results WHERE symbol = %s", (symbol,))
        conn.execute("DELETE FROM daily_bars WHERE symbol = %s", (symbol,))
        conn.execute("DELETE FROM theme_memberships WHERE symbol = %s", (symbol,))
        conn.execute("DELETE FROM stock_universe WHERE symbol = %s", (symbol,))


def _test_market_bundle():
    now = datetime.now(timezone.utc)
    source = live_source()
    temperature = MarketTemperature(
        score=56,
        label="均衡",
        advancers=2800,
        decliners=2200,
        limit_up_count=45,
        limit_down_count=12,
        total_turnover_billion=9150,
        updated_at=now,
    )
    indexes = [
        MarketIndex(symbol="000001.SH", name="上证指数", value=3120.25, change_pct=0.24, turnover_billion=3910, source_id=source.id),
        MarketIndex(symbol="399001.SZ", name="深证成指", value=9842.72, change_pct=-0.18, turnover_billion=5240, source_id=source.id),
        MarketIndex(symbol="399006.SZ", name="创业板指", value=1988.63, change_pct=0.41, turnover_billion=1900, source_id=source.id),
    ]
    sectors = [
        SectorSnapshot(
            name="银行",
            change_pct=1.26,
            turnover_billion=420,
            leading_symbols=["600000.SH"],
            driver="银行板块按实时涨幅排序靠前。",
            confidence=Confidence.medium,
            source_id=source.id,
        )
    ]
    watchlist = [
        item.model_copy(
            update={
                "name": item.name or "浦发银行",
                "price": 8.88,
                "change_pct": 1.23,
                "volume_ratio": 1.4,
                "latest_event": "实时行情：8.88，涨跌幅 +1.23%。",
                "source_id": source.id,
            }
        )
        for item in repositories.list_watchlist()
    ]
    events = [
        MarketEvent(
            id="live-test-breadth",
            occurred_at=now,
            type=EventType.capital_flow,
            title="A股市场宽度实时快照",
            summary="上涨 2800 家，下跌 2200 家。",
            affected_symbols=[],
            affected_sectors=[],
            importance="medium",
            fact_basis=["市场温度 56", "全市场成交额 9150 亿"],
            inference="市场温度来自实时涨跌家数，不构成方向预测。",
            confidence=Confidence.high,
            source_ids=[source.id],
            compliance_label="fact",
        )
    ]
    return temperature, indexes, sectors, watchlist, events, source


def _delete_tracking_test_rows() -> None:
    today = date.today()
    start, end = _day_window(today)
    with connect() as conn:
        conn.execute("DELETE FROM market_snapshots WHERE captured_at >= %s AND captured_at < %s", (start, end))
        conn.execute("DELETE FROM market_events WHERE id LIKE %s OR id LIKE %s", ("live-test-%", "rule-%"))
        conn.execute("DELETE FROM job_runs WHERE job_name IN ('intraday_snapshot', 'daily_report', 'news_explain', 'post_market_replay')", ())
        conn.execute("DELETE FROM news_items WHERE id LIKE %s", ("test-%",))
        conn.execute("DELETE FROM announcement_items WHERE id LIKE %s", ("test-%",))
        conn.execute("DELETE FROM daily_tracking_reports WHERE trading_day = %s", (today,))


def _assert_daily_report_mvp_shape(payload: dict) -> None:
    expected_titles = ["市场温度", "指数表现", "板块轮动", "盘中事件", "自选与观察池", "数据质量与缺口"]
    assert [section["title"] for section in payload["sections"]] == expected_titles
    assert all("summary" in section and "evidence" in section for section in payload["sections"])
    assert all(isinstance(section["evidence"], list) and section["evidence"] for section in payload["sections"])


def _assert_daily_report_compliance(payload: dict) -> None:
    forbidden_terms = ["买入", "卖出", "加仓", "减仓", "清仓", "满仓", "仓位", "目标价", "必涨", "稳赚", "保证收益"]
    text = " ".join(
        [
            payload["headline"],
            payload["summary"],
            *[
                " ".join(
                    [
                        section["title"],
                        section["summary"],
                        " ".join(section.get("evidence", [])),
                        " ".join(section.get("warnings", [])),
                    ]
                )
                for section in payload["sections"]
            ],
        ]
    )
    assert all(term not in text for term in forbidden_terms)


@pytest.fixture(autouse=True)
def no_external_market(monkeypatch):
    monkeypatch.setattr(main_module, "current_market", _test_market_bundle)
    monkeypatch.setattr(
        main_module,
        "fetch_quote_rows",
        lambda symbols: {
            symbol.upper(): {"f14": "浦发银行", "f2": 8.88, "f3": 1.23, "f10": 1.4}
            for symbol in symbols
        },
    )


def test_dashboard_contains_live_source_and_disclaimer():
    with TestClient(app) as client:
        response = client.get("/api/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert data["temperature"]["score"] >= 0
    assert data["sources"][0]["id"] == "src-eastmoney-live"
    assert "不构成证券投资建议" in data["disclaimer"]


def test_watchlist_create_update_delete_persists():
    symbol = "600000.SH"
    existing = repositories.get_watchlist_item(symbol)

    try:
        with TestClient(app) as client:
            client.delete(f"/api/watchlist/{symbol}")
            created = client.post(
                "/api/watchlist",
                json={
                    "symbol": symbol,
                    "group": "测试分组",
                    "tags": ["银行", "持久化"],
                },
            )
            assert created.status_code == 200
            assert created.json()["symbol"] == symbol
            assert created.json()["name"] == "浦发银行"
            assert created.json()["source_id"] == "src-eastmoney-live"

            watchlist = client.get("/api/watchlist")
            assert any(item["symbol"] == symbol for item in watchlist.json()["items"])

            patched = client.patch(f"/api/watchlist/{symbol}", json={"group": "已更新"})
            assert patched.status_code == 200
            assert patched.json()["group"] == "已更新"

            deleted = client.delete(f"/api/watchlist/{symbol}")
            assert deleted.status_code == 200
            assert deleted.json()["deleted"] is True
    finally:
        if existing is not None:
            repositories.upsert_watchlist_item(
                WatchlistItemCreate(
                    symbol=existing.symbol,
                    name=existing.name,
                    group=existing.group,
                    price=existing.price,
                    change_pct=existing.change_pct,
                    volume_ratio=existing.volume_ratio,
                    tags=existing.tags,
                    attention_reason=existing.attention_reason,
                    latest_event=existing.latest_event,
                    risk_flags=existing.risk_flags,
                    source_id=existing.source_id,
                )
            )


def test_assistant_answer_requires_citations_and_is_audited():
    query = "当前市场宽度如何？"
    with TestClient(app) as client:
        response = client.post("/api/assistant/query", json={"query": query})
        assert response.status_code == 200
        data = response.json()
        assert data["citations"]
        assert data["evidence"]
        assert data["blocked_by_compliance"] is False

        history = client.get("/api/admin/assistant-queries?limit=5")
        assert history.status_code == 200
        assert any(item["query"] == query for item in history.json()["items"])


def test_compliance_blocks_investment_advice():
    with TestClient(app) as client:
        response = client.post("/api/assistant/query", json={"query": "600000.SH 今天可以买入吗，仓位多少？"})
    assert response.status_code == 200
    data = response.json()
    assert data["blocked_by_compliance"] is True
    assert "不能提供证券投资建议" in data["answer"]


def test_replay_uses_live_snapshot_section():
    with TestClient(app) as client:
        response = client.get("/api/replay")
    assert response.status_code == 200
    data = response.json()
    windows = [section["window"] for section in data["sections"]]
    assert windows == ["实时快照"]
    assert data["sources"][0]["id"] == "src-eastmoney-live"


def _synthetic_bars(symbol: str, count: int = 130, breakout: bool = True) -> list[DailyBar]:
    start = date.today() - timedelta(days=count - 1)
    bars: list[DailyBar] = []
    for index in range(count):
        current = start + timedelta(days=index)
        base = 10 + (index % 6) * 0.02
        close = base
        high = base + 0.12
        low = base - 0.12
        amount = 80_000_000
        change_pct = 0.2
        if breakout and index == count - 1:
            close = 10.65
            high = 10.72
            low = 10.28
            amount = 220_000_000
            change_pct = 4.8
        bars.append(
            DailyBar(
                symbol=symbol,
                trade_date=current,
                open=base,
                high=high,
                low=low,
                close=close,
                volume=1_000_000 + index,
                amount=amount,
                change_pct=change_pct,
                turnover_rate=1.2,
            )
        )
    return bars


def _volume_price_bars(symbol: str, count: int = 130, end_day: date | None = None) -> list[DailyBar]:
    final_day = end_day or date.today()
    start = final_day - timedelta(days=count - 1)
    bars: list[DailyBar] = []
    for index in range(count):
        current = start + timedelta(days=index)
        close = 9.8 + index * 0.01
        open_price = close - 0.03
        high = close + 0.08
        low = close - 0.08
        amount = 75_000_000 + index * 120_000
        volume = 900_000 + index * 1500
        change_pct = 0.45
        turnover_rate = 4.5
        if index >= count - 5:
            step = index - (count - 5)
            amount = [96_000_000, 118_000_000, 145_000_000, 178_000_000, 235_000_000][step]
            volume = [1_050_000, 1_160_000, 1_320_000, 1_510_000, 1_760_000][step]
            turnover_rate = [4.2, 4.8, 5.5, 6.2, 7.1][step]
        if index == count - 1:
            open_price = close * 0.985
            close = close * 1.042
            high = close * 1.006
            low = open_price * 0.995
            change_pct = 4.2
        bars.append(
            DailyBar(
                symbol=symbol,
                trade_date=current,
                open=round(open_price, 3),
                high=round(high, 3),
                low=round(low, 3),
                close=round(close, 3),
                volume=volume,
                amount=amount,
                change_pct=change_pct,
                turnover_rate=turnover_rate,
            )
        )
    return bars


def test_stealth_scanner_identifies_launch_confirmation():
    symbol = "600888.SH"
    bars = _volume_price_bars(symbol)
    candidate = evaluate_candidate(
        StockUniverseItem(symbol=symbol, name="测试潜伏"),
        bars,
        themes=[ThemeMembership(symbol=symbol, theme_name="机器人", theme_type="concept")],
        active_themes=["机器人"],
        market_profile={"float_market_cap_billion": 126, "volume_ratio": 1.7},
    )
    assert candidate.stage in {"启动确认", "潜伏观察"}
    assert candidate.accumulation_score >= 65
    assert candidate.theme_score >= 70
    assert candidate.evidence


def test_mainboard_volume_price_strategy_identifies_matching_candidate():
    symbol = "600888.SH"
    candidate = evaluate_candidate(
        StockUniverseItem(symbol=symbol, name="测试主板启动", listed_days=900),
        _volume_price_bars(symbol),
        market_profile={"float_market_cap_billion": 126, "volume_ratio": 1.7},
    )

    assert candidate.stage in {"启动确认", "潜伏观察"}
    assert candidate.total_score >= 65
    assert candidate.metrics["strategy_profile"] == "mainboard_volume_price"
    assert candidate.metrics["float_market_cap_billion"] == 126
    assert candidate.metrics["volume_ratio"] == 1.7
    assert candidate.metrics["mainboard_match"] == "yes"
    assert candidate.metrics["ma_alignment"] == "bullish"
    assert candidate.metrics["intraday_proxy"] in {"strong_close", "partial"}
    assert any("主板量价启动" in item for item in candidate.evidence)


def test_mainboard_volume_price_strategy_excludes_wrong_board_and_missing_market_cap():
    wrong_board_symbol = "300888.SZ"
    wrong_board = evaluate_candidate(
        StockUniverseItem(symbol=wrong_board_symbol, name="测试创业板", listed_days=900),
        _volume_price_bars(wrong_board_symbol),
        market_profile={"float_market_cap_billion": 126, "volume_ratio": 1.7},
    )
    missing_cap_symbol = "600889.SH"
    missing_cap = evaluate_candidate(
        StockUniverseItem(symbol=missing_cap_symbol, name="测试缺市值", listed_days=900),
        _volume_price_bars(missing_cap_symbol),
        market_profile={"volume_ratio": 1.7},
    )

    assert wrong_board.stage == "数据不足"
    assert wrong_board.risk_penalty >= 80
    assert any("沪深主板" in risk for risk in wrong_board.risks)
    assert missing_cap.stage == "数据不足"
    assert any("流通市值" in risk for risk in missing_cap.risks)


def test_stealth_candidates_suppress_repeated_unobserved_same_stage():
    symbol = "600891.SH"
    _delete_stealth_test_symbol(symbol)
    try:
        candidates = []
        for days_ago in [2, 1, 0]:
            end_day = date.today() - timedelta(days=days_ago)
            candidate = evaluate_candidate(
                StockUniverseItem(symbol=symbol, name="测试重复", listed_days=900),
                _volume_price_bars(symbol, end_day=end_day),
                market_profile={"float_market_cap_billion": 118, "volume_ratio": 1.6},
            )
            candidates.append(candidate)
        save_scan_results(candidates)

        suppressed = list_candidates(limit=20, suppress_repeats=True, repeat_days=3)
        unsuppressed = list_candidates(limit=20, suppress_repeats=False, repeat_days=3)

        assert all(item.symbol != symbol for item in suppressed)
        assert any(item.symbol == symbol for item in unsuppressed)
    finally:
        _delete_stealth_test_symbol(symbol)


def test_stealth_scanner_marks_insufficient_history():
    symbol = "600889.SH"
    candidate = evaluate_candidate(StockUniverseItem(symbol=symbol, name="测试不足"), _synthetic_bars(symbol, count=30))
    assert candidate.stage == "数据不足"
    assert candidate.risks


def test_stealth_candidate_api_and_observation_flow():
    symbol = "600890.SH"
    _delete_stealth_test_symbol(symbol)
    bars = _volume_price_bars(symbol)
    candidate = evaluate_candidate(
        StockUniverseItem(symbol=symbol, name="测试观察"),
        bars,
        themes=[ThemeMembership(symbol=symbol, theme_name="半导体", theme_type="concept")],
        active_themes=["半导体"],
        market_profile={"float_market_cap_billion": 126, "volume_ratio": 1.7},
    )
    try:
        save_daily_bars(bars)
        save_scan_results([candidate])

        with TestClient(app) as client:
            listing = client.get("/api/stealth/candidates?limit=20")
            assert listing.status_code == 200
            assert any(item["symbol"] == symbol for item in listing.json())

            detail = client.get(f"/api/stealth/candidates/{symbol}")
            assert detail.status_code == 200
            assert detail.json()["candidate"]["symbol"] == symbol
            assert detail.json()["bars"]

            observed = client.post(
                f"/api/stealth/observe/{symbol}",
                json={
                    "reason": "启动确认",
                    "invalidation_rule": "跌回平台下沿后停止观察",
                    "next_focus": "继续观察量能是否放大",
                },
            )
            assert observed.status_code == 200
            assert observed.json()["symbol"] == symbol
            assert observed.json()["invalidation_rule"] == "跌回平台下沿后停止观察"
            assert observed.json()["next_focus"] == "继续观察量能是否放大"

            updated = client.patch(
                f"/api/stealth/observe/{symbol}",
                json={
                    "reason": "平台收敛",
                    "note": "人工备注",
                    "invalidation_rule": "跌破60日均线",
                    "next_focus": "观察同题材是否共振",
                },
            )
            assert updated.status_code == 200
            assert updated.json()["reason"] == "平台收敛"
            assert updated.json()["note"] == "人工备注"

            observations = client.get("/api/stealth/observations")
            assert observations.status_code == 200
            tracked = next(item for item in observations.json() if item["symbol"] == symbol)
            assert tracked["candidate"]["symbol"] == symbol
            assert tracked["candidate"]["observed"] is True
            assert isinstance(tracked["invalidation_reasons"], list)
            assert tracked["invalidation_rule"] == "跌破60日均线"
            assert tracked["next_focus"] == "观察同题材是否共振"

            summary = client.get("/api/stealth/observations/summary")
            assert summary.status_code == 200
            summary_payload = summary.json()
            assert summary_payload["total"] >= 1
            bucket_symbols = {
                bucket_item["symbol"]
                for bucket in summary_payload["buckets"]
                for bucket_item in bucket["items"]
            }
            assert symbol in bucket_symbols

            snapshot = client.post("/api/stealth/observations/journal/snapshot")
            assert snapshot.status_code == 200
            assert any(item["symbol"] == symbol for item in snapshot.json())
            journal_snapshot = next(item for item in snapshot.json() if item["symbol"] == symbol)
            assert journal_snapshot["manual_invalidation_rule"] == "跌破60日均线"
            assert journal_snapshot["next_focus"] == "观察同题材是否共振"

            journal = client.get(f"/api/stealth/observations/journal?symbol={symbol}")
            assert journal.status_code == 200
            journal_payload = journal.json()
            assert journal_payload[0]["symbol"] == symbol
            assert journal_payload[0]["bucket_label"] in {"继续观察", "启动确认", "失效检查", "待补扫"}
            assert journal_payload[0]["decision_summary"]

            deleted = client.delete(f"/api/stealth/observe/{symbol}")
            assert deleted.status_code == 200
            assert deleted.json()["deleted"] is True
    finally:
        _delete_stealth_test_symbol(symbol)


def test_stealth_diagnostics_returns_near_miss_without_polluting_candidates():
    symbol = "600890.SH"
    _delete_stealth_test_symbol(symbol)
    candidate = evaluate_candidate(
        StockUniverseItem(symbol=symbol, name="测试诊断"),
        _volume_price_bars(symbol),
        market_profile={"float_market_cap_billion": 126, "volume_ratio": 1.7},
    ).model_copy(
        update={
            "stage": "数据不足",
            "total_score": 22,
            "risks": ["未达到观察阈值：主板量价启动结构接近，但仍需继续观察。"],
        }
    )
    try:
        save_scan_results([candidate])
        with TestClient(app) as client:
            listing = client.get("/api/stealth/candidates?limit=200")
            assert listing.status_code == 200
            assert all(item["symbol"] != symbol for item in listing.json())

            diagnostics = client.get("/api/stealth/diagnostics?limit=20&min_score=1")
            assert diagnostics.status_code == 200
            payload = diagnostics.json()
            assert any(item["symbol"] == symbol for item in payload)
            assert any("未达到观察阈值" in risk for item in payload if item["symbol"] == symbol for risk in item["risks"])
    finally:
        _delete_stealth_test_symbol(symbol)


def test_stealth_scan_run_endpoint_creates_background_task(monkeypatch):
    now = datetime.now(timezone.utc)

    def fake_enqueue(request, active_themes):
        return StealthScanTask(
            id="test-task",
            status="queued",
            requested_limit=request.limit,
            requested_offset=request.offset,
            requested_symbols=request.symbols,
            active_themes=active_themes,
            total=0,
            scanned=0,
            saved=0,
            failed=0,
            stages={},
            message="扫描任务已排队。",
            error=None,
            created_at=now,
            started_at=None,
            finished_at=None,
            updated_at=now,
        )

    monkeypatch.setattr(main_module, "enqueue_stealth_scan_task", fake_enqueue)
    with TestClient(app) as client:
        response = client.post("/api/stealth/scan/run", json={"limit": 3, "offset": 500})
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["requested_limit"] == 3
    assert response.json()["requested_offset"] == 500


def test_stealth_observation_scan_enqueues_only_observed_symbols(monkeypatch):
    symbol = "600891.SH"
    _delete_stealth_test_symbol(symbol)
    now = datetime.now(timezone.utc)
    captured: dict[str, object] = {}

    def fake_enqueue(request, active_themes, include_watchlist=True):
        captured["include_watchlist"] = include_watchlist
        captured["symbols"] = request.symbols
        return StealthScanTask(
            id="observation-scan-task",
            status="queued",
            requested_limit=request.limit,
            requested_offset=request.offset,
            requested_symbols=request.symbols,
            active_themes=active_themes,
            total=0,
            scanned=0,
            saved=0,
            failed=0,
            stages={},
            message="观察池补扫任务已排队。",
            error=None,
            created_at=now,
            started_at=None,
            finished_at=None,
            updated_at=now,
        )

    monkeypatch.setattr(main_module, "enqueue_stealth_scan_task", fake_enqueue)
    try:
        with TestClient(app) as client:
            observed = client.post(f"/api/stealth/observe/{symbol}", json={"reason": "测试观察池补扫"})
            assert observed.status_code == 200

            response = client.post("/api/stealth/observations/scan")
        assert response.status_code == 200
        assert response.json()["id"] == "observation-scan-task"
        assert symbol in captured["symbols"]
        assert captured["include_watchlist"] is False
    finally:
        _delete_stealth_test_symbol(symbol)


def test_stealth_scan_monitor_endpoint():
    with TestClient(app) as client:
        response = client.get("/api/stealth/scan/monitor")
    assert response.status_code == 200
    payload = response.json()
    assert "latest_tasks" in payload
    assert "data_quality" in payload
    assert "alerts" in payload


def test_admin_agents_includes_data_source_statuses(monkeypatch):
    monkeypatch.setenv("MARKETLENS_MARKET_PROVIDER", "ths")
    monkeypatch.delenv("THS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("THS_REFRESH_TOKEN", raising=False)

    with TestClient(app) as client:
        response = client.get("/api/admin/agents")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data_sources"]
    assert "data_source_statuses" in payload
    market_status = next(item for item in payload["data_source_statuses"] if item["id"] == "src-ths-quantapi-market")
    assert market_status["status"] == "missing_credentials"
    assert market_status["capabilities"]["quotes"] == "needs_token"


def test_stealth_scan_failure_listing_and_retry(monkeypatch):
    now = datetime.now(timezone.utc)
    created_retry_ids: list[str] = []

    def fake_retry(task_id, active_themes):
        retry = StealthScanTask(
            id="retry-task",
            status="queued",
            requested_limit=None,
            requested_offset=0,
            requested_symbols=["000001.SZ"],
            active_themes=active_themes,
            total=0,
            scanned=0,
            saved=0,
            failed=0,
            stages={},
            message="失败项已重新排队。",
            error=None,
            created_at=now,
            started_at=None,
            finished_at=None,
            updated_at=now,
        )
        created_retry_ids.append(retry.id)
        assert task_id == task.id
        return retry

    monkeypatch.setattr(main_module, "enqueue_failed_symbols_retry", fake_retry)
    with TestClient(app) as client:
        task = create_scan_task(requested_limit=1, requested_offset=0, requested_symbols=["000001.SZ"], active_themes=[])
        try:
            record_scan_failure(task.id, "000001.SZ", "平安银行", "daily_bars", "timeout")

            failures = client.get(f"/api/stealth/scan/tasks/{task.id}/failures")
            assert failures.status_code == 200
            payload = failures.json()
            assert payload[0]["symbol"] == "000001.SZ"
            assert payload[0]["stage"] == "daily_bars"
            assert payload[0]["resolved"] is False

            retry = client.post(f"/api/stealth/scan/tasks/{task.id}/retry-failures")
            assert retry.status_code == 200
            assert retry.json()["id"] == "retry-task"
            assert retry.json()["requested_symbols"] == ["000001.SZ"]

            resolved = client.post(f"/api/stealth/scan/tasks/{task.id}/resolve-failures")
            assert resolved.status_code == 200
            assert resolved.json()["resolved"] == 1

            unresolved = client.get(f"/api/stealth/scan/tasks/{task.id}/failures?unresolved_only=true")
            assert unresolved.status_code == 200
            assert unresolved.json() == []
        finally:
            with connect() as conn:
                conn.execute("DELETE FROM stealth_scan_tasks WHERE id = %s", (task.id,))


class _FakeTrackingMarketProvider:
    def current_bundle(self, watchlist):
        temperature, indexes, sectors, watchlist_items, events, source = _test_market_bundle()
        meta = ProviderMeta(
            provider="test-provider",
            source_id=source.id,
            fetched_at=datetime.now(timezone.utc),
            license_note=source.license,
        )
        return temperature, indexes, sectors, watchlist_items, events, meta


class _FakeSequentialTrackingMarketProvider:
    def __init__(self):
        self.calls = 0

    def current_bundle(self, watchlist):
        temperature, indexes, sectors, watchlist_items, events, source = _test_market_bundle()
        captured_at = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=self.calls * 5)
        if self.calls == 0:
            temperature = temperature.model_copy(update={"score": 42, "advancers": 1900, "decliners": 3100, "updated_at": captured_at})
            sectors = [sectors[0].model_copy(update={"name": "银行", "change_pct": 0.6})]
        else:
            temperature = temperature.model_copy(update={"score": 68, "advancers": 3500, "decliners": 1500, "updated_at": captured_at})
            sectors = [sectors[0].model_copy(update={"name": "半导体", "change_pct": 3.2})]
        events = [
            events[0].model_copy(
                update={
                    "id": f"live-test-breadth-{self.calls}",
                    "occurred_at": captured_at,
                    "title": f"A股市场宽度实时快照 {self.calls + 1}",
                }
            )
        ]
        self.calls += 1
        meta = ProviderMeta(
            provider="test-provider",
            source_id=source.id,
            fetched_at=captured_at,
            license_note=source.license,
        )
        return temperature, indexes, sectors, watchlist_items, events, meta


class _FakeNewsAnnouncementProvider:
    def news(self, symbols):
        now = datetime.now(timezone.utc)
        return [
            NewsItem(
                id="test-news-600000",
                symbol="600000.SH",
                title="测试新闻摘要",
                summary="仅保存标题、摘要、链接和来源。",
                published_at=now,
                source_url="https://example.com/news/1",
                source_name="测试来源",
                source_id="src-test-news",
                provider="test-provider",
                license_note="测试研发源",
            )
        ]

    def announcements(self, symbols):
        now = datetime.now(timezone.utc)
        return [
            AnnouncementItem(
                id="test-announcement-600000",
                symbol="600000.SH",
                title="测试公告摘要",
                summary="公告解释必须带来源。",
                published_at=now,
                source_url="https://example.com/announcement/1",
                source_name="测试公告源",
                source_id="src-test-announcement",
                provider="test-provider",
                license_note="测试研发源",
            )
        ]


def test_tracking_daily_report_without_snapshots_marks_data_gaps():
    _delete_tracking_test_rows()
    try:
        with TestClient(app) as client:
            report = client.get(f"/api/tracking/daily?date={date.today().isoformat()}")
        assert report.status_code == 200
        payload = report.json()
        assert payload["snapshots"] == []
        assert payload["source_ids"]
        assert "快照不足，分析置信度低" in payload["headline"]
        _assert_daily_report_mvp_shape(payload)
        _assert_daily_report_compliance(payload)
        data_quality = next(section for section in payload["sections"] if section["title"] == "数据质量与缺口")
        assert any("新闻/公告源未接入" in warning for warning in data_quality["warnings"])
        assert any("快照不足" in warning for warning in data_quality["warnings"])
    finally:
        _delete_tracking_test_rows()


def test_tracking_job_run_creates_snapshot_and_report(monkeypatch):
    _delete_tracking_test_rows()
    monkeypatch.setattr(tracking_service, "market_data_provider", _FakeTrackingMarketProvider())
    try:
        with TestClient(app) as client:
            run = client.post("/api/admin/jobs/run/intraday_snapshot")
            assert run.status_code == 200
            assert run.json()["status"] == "completed"

            runs = client.get("/api/admin/jobs/runs?limit=5")
            assert runs.status_code == 200
            assert any(item["job_name"] == "intraday_snapshot" for item in runs.json())

            snapshots = client.get(f"/api/tracking/snapshots?date={date.today().isoformat()}&interval=5m")
            assert snapshots.status_code == 200
            assert snapshots.json()
            assert snapshots.json()[0]["provider"] == "test-provider"

            events = client.get(f"/api/tracking/events?date={date.today().isoformat()}")
            assert events.status_code == 200
            assert events.json()

            report_run = client.post("/api/admin/jobs/run/daily_report")
            assert report_run.status_code == 200
            assert report_run.json()["status"] == "completed"

            report = client.get(f"/api/tracking/daily?date={date.today().isoformat()}")
            assert report.status_code == 200
            payload = report.json()
            assert payload["snapshots"]
            assert payload["events"]
            assert payload["source_ids"]
            _assert_daily_report_mvp_shape(payload)
            _assert_daily_report_compliance(payload)
            assert payload["sections"][0]["metrics"]["snapshots"] == 1
            assert any("快照不足" in warning for warning in payload["sections"][0]["warnings"])
            event_section = next(section for section in payload["sections"] if section["title"] == "盘中事件")
            assert any("新闻/公告源未接入" in warning for warning in event_section["warnings"])
    finally:
        _delete_tracking_test_rows()


def test_tracking_daily_report_with_multiple_snapshots_tracks_changes(monkeypatch):
    _delete_tracking_test_rows()
    monkeypatch.setattr(tracking_service, "market_data_provider", _FakeSequentialTrackingMarketProvider())
    try:
        with TestClient(app) as client:
            first = client.post("/api/admin/jobs/run/intraday_snapshot")
            second = client.post("/api/admin/jobs/run/intraday_snapshot")
            assert first.status_code == 200
            assert second.status_code == 200

            report_run = client.post("/api/admin/jobs/run/daily_report")
            assert report_run.status_code == 200

            report = client.get(f"/api/tracking/daily?date={date.today().isoformat()}")
        assert report.status_code == 200
        payload = report.json()
        _assert_daily_report_mvp_shape(payload)
        _assert_daily_report_compliance(payload)
        assert len(payload["snapshots"]) == 2
        market_section = next(section for section in payload["sections"] if section["title"] == "市场温度")
        assert market_section["metrics"]["snapshots"] == 2
        assert market_section["metrics"]["score_delta"] == 26
        assert "warnings" not in market_section
        sector_section = next(section for section in payload["sections"] if section["title"] == "板块轮动")
        assert "切换至 半导体" in sector_section["summary"]
    finally:
        _delete_tracking_test_rows()


def test_tracking_news_and_announcements_endpoints(monkeypatch):
    _delete_tracking_test_rows()
    monkeypatch.setattr(tracking_service, "news_announcement_provider", _FakeNewsAnnouncementProvider())
    try:
        with TestClient(app) as client:
            run = client.post("/api/admin/jobs/run/news_explain")
            assert run.status_code == 200
            assert run.json()["status"] == "completed"

            news = client.get(f"/api/news?date={date.today().isoformat()}&symbol=600000.SH")
            assert news.status_code == 200
            assert news.json()[0]["title"] == "测试新闻摘要"
            assert news.json()[0]["source_url"]

            announcements = client.get(f"/api/announcements?date={date.today().isoformat()}&symbol=600000.SH")
            assert announcements.status_code == 200
            assert announcements.json()[0]["title"] == "测试公告摘要"
            assert announcements.json()[0]["source_url"]
    finally:
        _delete_tracking_test_rows()


def test_tracking_information_summary_groups_news_and_announcements(monkeypatch):
    _delete_tracking_test_rows()
    monkeypatch.setattr(tracking_service, "news_announcement_provider", _FakeNewsAnnouncementProvider())
    try:
        with TestClient(app) as client:
            run = client.post("/api/admin/jobs/run/news_explain")
            assert run.status_code == 200

            response = client.get(f"/api/tracking/information-summary?date={date.today().isoformat()}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["trading_day"] == date.today().isoformat()
        assert payload["total_count"] == 2
        assert payload["news_count"] == 1
        assert payload["announcement_count"] == 1
        assert payload["by_importance"]["medium"] == 2
        assert payload["by_event_type"] == {"announcement": 1, "news": 1}
        assert payload["by_symbol"][0]["symbol"] == "600000.SH"
        assert payload["by_symbol"][0]["total"] == 2
        assert payload["by_symbol"][0]["announcements"] == 1
        assert payload["latest_items"][0]["source_id"] in {"src-test-news", "src-test-announcement"}
        assert not payload["warnings"]
    finally:
        _delete_tracking_test_rows()
