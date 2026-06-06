from datetime import date

from backend.app.data_providers import (
    AkshareCninfoAnnouncementProvider,
    TonghuashunDelayedHistoryProvider,
    TushareNewsAnnouncementProvider,
    data_source_statuses,
    history_provider_sources,
    information_provider_sources,
)
from backend.app.history_provider import HistoryDataUnavailable
from backend.app.models import DailyBar
from backend.app.ths_provider import TonghuashunQuantApiClient


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_tushare_announcement_provider_maps_announcements(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return _FakeResponse(
            {
                "code": 0,
                "msg": "",
                "data": {
                    "fields": ["ts_code", "name", "title", "ann_date", "url"],
                    "items": [
                        ["600000.SH", "浦发银行", "浦发银行关于重大事项的公告", "20260531", "https://example.com/a.pdf"],
                        ["000001.SZ", "平安银行", "平安银行普通公告", "20260531", "https://example.com/b.pdf"],
                    ],
                },
            }
        )

    monkeypatch.setattr("backend.app.data_providers.requests.post", fake_post)
    provider = TushareNewsAnnouncementProvider(token="test-token", endpoint="https://api.example.test", timeout_seconds=3)

    items = provider.announcements(["600000.SH"])

    assert calls[0]["json"]["api_name"] == "anns_d"
    assert calls[0]["json"]["token"] == "test-token"
    assert items[0].symbol == "600000.SH"
    assert items[0].importance == "high"
    assert items[0].source_id == "src-tushare-announcement"
    assert len(items) == 1


def test_tushare_news_provider_maps_and_filters_news(monkeypatch):
    def fake_post(url, json, timeout):
        return _FakeResponse(
            {
                "code": 0,
                "msg": "",
                "data": {
                    "fields": ["datetime", "title", "content", "src", "url"],
                    "items": [
                        ["2026-05-31 09:30:00", "600000 相关快讯", "公司公告引发关注", "sina", "https://example.com/news"],
                        ["2026-05-31 09:31:00", "其他市场快讯", "不含自选代码", "sina", "https://example.com/other"],
                    ],
                },
            }
        )

    monkeypatch.setattr("backend.app.data_providers.requests.post", fake_post)
    provider = TushareNewsAnnouncementProvider(token="test-token", endpoint="https://api.example.test", timeout_seconds=3)

    items = provider.news(["600000.SH"])

    assert len(items) == 1
    assert items[0].symbol == "600000.SH"
    assert items[0].source_id == "src-tushare-news"
    assert items[0].provider == "tushare-pro-info"


def test_tushare_provider_requires_token(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    provider = TushareNewsAnnouncementProvider(token="")

    try:
        provider.announcements()
    except RuntimeError as exc:
        assert "TUSHARE_TOKEN" in str(exc)
    else:
        raise AssertionError("expected missing token error")


def test_akshare_cninfo_announcement_provider_maps_and_filters_announcements(monkeypatch):
    calls = []

    class FakeFrame:
        def to_dict(self, orient):
            assert orient == "records"
            return [
                {
                    "代码": "600000",
                    "简称": "浦发银行",
                    "公告标题": "浦发银行关于重大事项的公告",
                    "公告时间": "2026-05-31 16:00:00",
                    "公告链接": "https://static.cninfo.com.cn/finalpage/a.pdf",
                },
                {
                    "代码": "000001",
                    "简称": "平安银行",
                    "公告标题": "平安银行普通公告",
                    "公告时间": "2026-05-31 16:00:00",
                    "公告链接": "https://static.cninfo.com.cn/finalpage/b.pdf",
                },
            ]

    def fake_fetch(**kwargs):
        calls.append(kwargs)
        return FakeFrame()

    monkeypatch.setattr("backend.app.data_providers._akshare_cninfo_disclosure_report", fake_fetch)
    provider = AkshareCninfoAnnouncementProvider(category="公司治理", limit=10)

    items = provider.announcements(["600000.SH"])

    assert calls[0]["symbol"] == "600000"
    assert calls[0]["market"] == "沪深京"
    assert calls[0]["category"] == "公司治理"
    assert items[0].symbol == "600000.SH"
    assert items[0].importance == "high"
    assert items[0].source_id == "src-cninfo-announcement"
    assert items[0].provider == "akshare-cninfo-announcement"
    assert len(items) == 1


def test_akshare_cninfo_source_and_status(monkeypatch):
    monkeypatch.setenv("MARKETLENS_INFO_PROVIDER", "akshare_cninfo")
    monkeypatch.setattr(
        "backend.app.data_providers.news_announcement_provider",
        AkshareCninfoAnnouncementProvider(),
    )

    sources = information_provider_sources()
    statuses = {status.id: status for status in data_source_statuses()}

    assert sources[0].id == "src-cninfo-announcement"
    assert statuses["src-cninfo-announcement"].status == "configured"
    assert statuses["src-cninfo-announcement"].capabilities == {
        "announcements": "configured",
        "news": "not_enabled",
    }


def test_tonghuashun_quantapi_client_maps_history_bars(monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if url.endswith("/get_access_token"):
            return _FakeResponse({"errorcode": 0, "data": {"access_token": "access-token"}})
        return _FakeResponse(
            {
                "errorcode": 0,
                "tables": [
                    {
                        "thscode": "600000.SH",
                        "time": ["2026-05-28", "2026-05-29"],
                        "table": {
                            "open": [10.0, 10.5],
                            "high": [10.8, 11.0],
                            "low": [9.9, 10.2],
                            "close": [10.4, 10.8],
                            "volume": [1000, 1200],
                            "amount": [1000000, 1300000],
                            "changeRatio": [1.2, 3.85],
                            "turnoverRatio": [0.4, 0.5],
                        },
                    }
                ],
            }
        )

    monkeypatch.setattr("backend.app.ths_provider.requests.post", fake_post)
    client = TonghuashunQuantApiClient(refresh_token="refresh-token", base_url="https://quantapi.example/api/v1", timeout_seconds=3)

    bars = client.history_bars("600000.SH", days=2)

    assert calls[0]["url"].endswith("/get_access_token")
    assert calls[1]["headers"]["access_token"] == "access-token"
    assert calls[1]["json"]["codes"] == "600000.SH"
    assert bars[0].symbol == "600000.SH"
    assert bars[0].trade_date == date(2026, 5, 28)
    assert bars[-1].close == 10.8
    assert bars[-1].turnover_rate == 0.5


def test_tonghuashun_quantapi_client_maps_realtime_quotes(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        if url.endswith("/get_access_token"):
            return _FakeResponse({"errorcode": 0, "data": {"access_token": "access-token"}})
        assert url.endswith("/real_time_quotation")
        return _FakeResponse(
            {
                "errorcode": 0,
                "tables": [
                    {
                        "thscode": "600000.SH",
                        "table": {
                            "latest": [10.8],
                            "changeRatio": [2.5],
                            "amount": [1300000],
                            "volumeRatio": [1.2],
                        },
                    }
                ],
            }
        )

    monkeypatch.setattr("backend.app.ths_provider.requests.post", fake_post)
    client = TonghuashunQuantApiClient(refresh_token="refresh-token", base_url="https://quantapi.example/api/v1", timeout_seconds=3)

    quotes = client.real_time_quotes(["600000.SH"])

    assert quotes["600000.SH"]["latest"] == 10.8
    assert quotes["600000.SH"]["changeRatio"] == 2.5


def test_tonghuashun_quantapi_client_maps_announcements(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        if url.endswith("/get_access_token"):
            return _FakeResponse({"errorcode": 0, "data": {"access_token": "access-token"}})
        assert url.endswith("/report_query")
        return _FakeResponse(
            {
                "errorcode": 0,
                "tables": [
                    {
                        "thscode": "600000.SH",
                        "time": ["2026-05-31"],
                        "table": {
                            "reportDate": ["2026-05-31"],
                            "secName": ["浦发银行"],
                            "reportTitle": ["浦发银行关于重大事项的公告"],
                            "pdfURL": ["https://example.com/a.pdf"],
                            "seq": ["1"],
                        },
                    }
                ],
            }
        )

    monkeypatch.setattr("backend.app.ths_provider.requests.post", fake_post)
    client = TonghuashunQuantApiClient(refresh_token="refresh-token", base_url="https://quantapi.example/api/v1", timeout_seconds=3)

    items = client.announcements(["600000.SH"], begin_date=date(2026, 5, 31), end_date=date(2026, 5, 31))

    assert items[0].symbol == "600000.SH"
    assert items[0].importance == "high"
    assert items[0].source_id == "src-ths-quantapi-announcement"


def test_tonghuashun_history_provider_falls_back_to_akshare():
    class BrokenClient:
        def history_bars(self, symbol, *, days, period="D", adjust="qfq"):
            raise HistoryDataUnavailable("ths unavailable")

    class Fallback:
        source_ids = ["src-akshare-dev"]

        def stock_universe(self):
            return []

        def daily_bars(self, symbol, days=250):
            return [
                DailyBar(
                    symbol=symbol,
                    trade_date=date(2026, 5, 29),
                    open=1,
                    high=1,
                    low=1,
                    close=1,
                )
            ]

        def weekly_bars(self, symbol, weeks=80):
            return []

        def theme_memberships(self, symbols):
            return []

    provider = TonghuashunDelayedHistoryProvider(client=BrokenClient(), fallback=Fallback(), allow_bar_fallback=True)

    assert provider.daily_bars("600000.SH")[0].symbol == "600000.SH"


def test_tonghuashun_history_sources_omit_akshare_when_akshare_fallbacks_disabled(monkeypatch):
    monkeypatch.setenv("THS_HISTORY_FALLBACK_TO_AKSHARE", "0")
    monkeypatch.setenv("THS_THEME_FALLBACK_TO_AKSHARE", "0")
    monkeypatch.setattr(
        "backend.app.data_providers.history_data_provider",
        TonghuashunDelayedHistoryProvider(),
    )

    source_ids = [source.id for source in history_provider_sources()]

    assert source_ids == ["src-ths-quantapi-delayed"]


def test_tonghuashun_data_source_status_marks_missing_credentials(monkeypatch):
    monkeypatch.setenv("MARKETLENS_MARKET_PROVIDER", "ths")
    monkeypatch.setenv("MARKETLENS_HISTORY_PROVIDER", "ths_quantapi")
    monkeypatch.setenv("MARKETLENS_INFO_PROVIDER", "ifind")
    monkeypatch.delenv("THS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("THS_REFRESH_TOKEN", raising=False)

    statuses = {status.id: status for status in data_source_statuses()}

    assert statuses["src-ths-quantapi-market"].status == "missing_credentials"
    assert statuses["src-ths-quantapi-market"].capabilities == {
        "quotes": "needs_token",
        "indexes": "needs_token",
        "ranked_groups": "needs_token",
    }
    assert "THS_REFRESH_TOKEN" in statuses["src-ths-quantapi-market"].next_step
    assert "THS_ACCESS_TOKEN" in statuses["src-ths-quantapi-market"].next_step
    assert statuses["src-ths-quantapi-delayed"].capabilities["history_bars"] == "needs_token"
    assert statuses["src-ths-quantapi-announcement"].capabilities["announcements"] == "needs_token"


def test_tonghuashun_data_source_status_marks_configured_credentials(monkeypatch):
    monkeypatch.setenv("MARKETLENS_MARKET_PROVIDER", "tonghuashun")
    monkeypatch.setenv("MARKETLENS_HISTORY_PROVIDER", "ifind")
    monkeypatch.setenv("MARKETLENS_INFO_PROVIDER", "ths_quantapi")
    monkeypatch.setenv("THS_ACCESS_TOKEN", "access-token")
    monkeypatch.delenv("THS_REFRESH_TOKEN", raising=False)
    monkeypatch.setenv("THS_THEME_FALLBACK_TO_AKSHARE", "0")

    statuses = {status.id: status for status in data_source_statuses()}

    assert statuses["src-ths-quantapi-market"].status == "configured"
    assert statuses["src-ths-quantapi-market"].capabilities == {
        "quotes": "configured",
        "indexes": "configured",
        "ranked_groups": "configured",
    }
    assert statuses["src-ths-quantapi-delayed"].status == "configured"
    assert statuses["src-ths-quantapi-delayed"].capabilities == {
        "history_bars": "configured",
        "stock_universe": "configured",
        "theme_memberships": "not_enabled",
    }
    assert statuses["src-ths-quantapi-announcement"].capabilities == {
        "announcements": "configured",
        "news": "not_enabled",
    }
