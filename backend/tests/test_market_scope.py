from datetime import date

from backend.app import stealth_scanner
from backend.app.market_scope import is_mainboard_eligible, is_mainboard_symbol
from backend.app.database import connect, init_schema
from backend.app.models import DailyBar, StockUniverseItem
from backend.app.stealth_repository import build_data_quality_summary, save_daily_bars, save_universe_items


def _bar(symbol: str) -> DailyBar:
    return DailyBar(
        symbol=symbol,
        trade_date=date(2026, 6, 5),
        open=10,
        high=10.2,
        low=9.8,
        close=10,
        volume=1_000_000,
        amount=100_000_000,
        change_pct=0,
        turnover_rate=1,
    )


def test_mainboard_scope_accepts_only_shanghai_and_shenzhen_mainboard():
    accepted = ["600000.SH", "601000.SH", "603000.SH", "605000.SH", "000001.SZ", "001000.SZ", "002001.SZ", "003001.SZ"]
    rejected = [
        "688001.SH",
        "300001.SZ",
        "301001.SZ",
        "920001.BJ",
        "830001.BJ",
        "430001.BJ",
        "900001.SH",
        "200001.SZ",
        "600000.BJ",
        "600000",
        "600ABC.SH",
        "60000.SH",
    ]

    assert all(is_mainboard_symbol(symbol) for symbol in accepted)
    assert all(not is_mainboard_symbol(symbol) for symbol in rejected)


def test_mainboard_scope_rejects_st_and_delisting_names():
    assert is_mainboard_eligible(StockUniverseItem(symbol="600000.SH", name="浦发银行"))
    assert not is_mainboard_eligible(StockUniverseItem(symbol="600001.SH", name="ST 测试"))
    assert not is_mainboard_eligible(StockUniverseItem(symbol="600002.SH", name="*ST测试"))
    assert not is_mainboard_eligible(StockUniverseItem(symbol="600003.SH", name="退市测试"))
    assert not is_mainboard_eligible(StockUniverseItem(symbol="600004.SH", name="正常名称", is_st=True))


def test_scan_filters_out_non_mainboard_and_st_before_loading_history(monkeypatch):
    universe = [
        StockUniverseItem(symbol="600000.SH", name="沪市主板"),
        StockUniverseItem(symbol="000001.SZ", name="深市主板"),
        StockUniverseItem(symbol="688001.SH", name="科创板"),
        StockUniverseItem(symbol="300001.SZ", name="创业板"),
        StockUniverseItem(symbol="301001.SZ", name="创业板二"),
        StockUniverseItem(symbol="920001.BJ", name="北交所"),
        StockUniverseItem(symbol="600001.SH", name="ST测试", is_st=True),
    ]
    loaded: list[str] = []

    class FakeProvider:
        def stock_universe(self):
            return universe

        def daily_bars(self, symbol):
            loaded.append(symbol)
            return [_bar(symbol)]

        def weekly_bars(self, symbol):
            return []

        def theme_memberships(self, symbols):
            return []

    monkeypatch.setattr(stealth_scanner, "history_data_provider", FakeProvider())
    monkeypatch.setattr(stealth_scanner, "history_data_source_ids", lambda _: ["test"])
    monkeypatch.setattr(stealth_scanner, "fetch_stock_market_profiles", lambda _: {})
    monkeypatch.setattr(stealth_scanner, "save_universe_items", lambda _: None)
    monkeypatch.setattr(stealth_scanner, "save_daily_bars", lambda _: None)
    monkeypatch.setattr(stealth_scanner, "save_theme_memberships", lambda _: None)
    monkeypatch.setattr(stealth_scanner, "save_scan_results", lambda _: None)

    result = stealth_scanner.run_stealth_scan(include_watchlist=False)

    assert result.total == 2
    assert loaded == ["600000.SH", "000001.SZ"]

    unknown = stealth_scanner.run_stealth_scan(symbols=["600099.SH"], include_watchlist=False)
    assert unknown.total == 0
    assert loaded == ["600000.SH", "000001.SZ"]


def test_strategy_data_quality_counts_only_non_st_mainboard_rows():
    init_schema()
    before = build_data_quality_summary()
    day = before.latest_trade_date or date(2026, 6, 5)
    items = [
        StockUniverseItem(symbol="600096.SH", name="主板样本"),
        StockUniverseItem(symbol="600095.SH", name="ST样本", is_st=True),
        StockUniverseItem(symbol="300096.SZ", name="创业板样本"),
    ]
    bars = [_bar(item.symbol).model_copy(update={"trade_date": day}) for item in items]
    save_universe_items(items)
    save_daily_bars(bars)
    try:
        quality = build_data_quality_summary()
        assert quality.latest_trade_date == day
        assert quality.latest_bar_symbols == before.latest_bar_symbols + 1
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM daily_bars WHERE symbol = ANY(%s)", ([item.symbol for item in items],))
            conn.execute("DELETE FROM stock_universe WHERE symbol = ANY(%s)", ([item.symbol for item in items],))
