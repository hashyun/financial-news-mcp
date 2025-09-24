import pytest
import server
from types import SimpleNamespace
from dateutil import parser as dateparser
import finance_news.data_sources as data_sources
import finance_news.network as network
import finance_news.tools as tools


class DummyResp:
    def __init__(self, *, json_data=None, text_data=None):
        self._json = json_data
        self.text = text_data
    def json(self):
        return self._json
    def raise_for_status(self):
        pass


def test_fetch_yahoo_chart(monkeypatch):
    data = {
        "chart": {
            "result": [
                {
                    "timestamp": [1, 2],
                    "indicators": {
                        "quote": [
                            {
                                "open": [1, 2],
                                "high": [2, 3],
                                "low": [0.5, 1.5],
                                "close": [1.5, 2.5],
                                "volume": [100, 200],
                            }
                        ]
                    },
                }
            ]
        }
    }
    def fake_get(url, *, params=None, timeout=30):
        return DummyResp(json_data=data)
    monkeypatch.setattr(data_sources, "_http_get", fake_get)
    res = server._fetch_yahoo_chart("TEST", range_="1d", interval="1h")
    assert res["symbol"] == "TEST"
    assert len(res["points"]) == 2
    assert res["summary"]["pct_change"] == pytest.approx((2.5 - 1.5) / 1.5 * 100)


def test_google_news_rss(monkeypatch):
    rss = (
        "<rss version='2.0'><channel>"
        "<item><title>T1</title><link>http://ex/1</link><description>Desc1</description>"
        "<pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate></item>"
        "<item><title>T2</title><link>http://ex/2</link><description>Desc2</description>"
        "<pubDate>Tue, 02 Jan 2024 00:00:00 GMT</pubDate></item>"
        "</channel></rss>"
    )
    def fake_get(url, *, params=None, timeout=20):
        return DummyResp(text_data=rss)
    monkeypatch.setattr(data_sources, "_http_get", fake_get)
    items = server._google_news_rss("apple", lang="en", region="US")
    assert len(items) == 2
    assert items[0]["source"] == "Google News"
    assert items[0]["title"] == "T1"
    assert items[1]["link"] == "http://ex/2"


def test_google_news_rss_handles_errors(monkeypatch):
    def fake_get(url, *, params=None, timeout=20):
        raise RuntimeError("boom")

    monkeypatch.setattr(data_sources, "_http_get", fake_get)
    items = server._google_news_rss("apple")
    assert items == []


def test_normalize_article():
    entry = {
        "title": "Example",
        "summary": "<p>Hello <b>World</b></p>",
        "link": "http://example.com",
        "published": "2024-01-01T00:00:00Z",
    }
    res = server._normalize_article("MySource", entry)
    assert res["source"] == "MySource"
    assert res["title"] == "Example"
    assert res["summary"] == "Hello World"
    assert res["link"] == "http://example.com"
    assert res["published"] == "2024-01-01T00:00:00+00:00"


def test_yahoo_options_chain(monkeypatch):
    data = {"optionChain": {"result": [{"expirationDates": [1, 2]}]}}
    captured = {}

    def fake_get(url, *, params=None, timeout=30):
        captured["params"] = params
        return DummyResp(json_data=data)

    monkeypatch.setattr(data_sources, "_http_get", fake_get)
    res = server._yahoo_options_chain("AAPL", expiration="2024-01-01")
    assert res == data
    expected = int(dateparser.parse("2024-01-01").timestamp())
    assert captured["params"]["date"] == expected


def test_fred_fetch(monkeypatch):
    def fake_get(url, *, params=None, timeout=30):
        return DummyResp(json_data={"id": params["series_id"]})

    monkeypatch.setenv("FRED_API_KEY", "key")
    monkeypatch.setattr(data_sources, "_http_get", fake_get)
    args = SimpleNamespace(series_ids=["S1", "S2"], start=None, end=None, frequency=None, aggregation_method=None)
    res = server._fred_fetch(args)
    assert res["S1"]["id"] == "S1"
    assert res["S2"]["id"] == "S2"


def test_ecos_series_forwards_args(monkeypatch):
    captured = {}

    def fake_fetch(args):
        captured["stat_code"] = args.stat_code
        captured["item_code2"] = args.item_code2
        return {"ok": True}

    monkeypatch.setattr(tools, "_ecos_fetch", fake_fetch)
    args = tools.EcosArgs(
        stat_code="722Y001",
        start="20200101",
        end="20200201",
        cycle="M",
        item_code1="A",
        item_code2="B",
    )
    res = tools.ecos_series(args)
    assert res == {"ok": True}
    assert captured["stat_code"] == "722Y001"
    assert captured["item_code2"] == "B"


def test_ecos_series_missing_api_key(monkeypatch):
    monkeypatch.delenv("BOK_API_KEY", raising=False)
    args = tools.EcosArgs(stat_code="722Y001", start="20200101", end="20200201", cycle="M")
    res = tools.ecos_series(args)
    assert res == {"error": "missing_api_key", "env": "BOK_API_KEY"}


def test_dart_filings(monkeypatch):
    data = {"status": "013", "list": []}

    def fake_get(url, *, params=None, timeout=30):
        return DummyResp(json_data=data)

    monkeypatch.setenv("DART_API_KEY", "key")
    monkeypatch.setattr(data_sources, "_http_get", fake_get)
    res = server._dart_filings(corp_code="12345678", page_count=5)
    assert res["status"] == "013"


def test_http_get_rejects_non_https():
    with pytest.raises(ValueError) as exc:
        network._http_get("http://query1.finance.yahoo.com/test")
    assert "https_required" in str(exc.value)


def test_http_get_rejects_unknown_host(monkeypatch):
    monkeypatch.setattr(network, "STRICT_SECURITY", True)
    with pytest.raises(ValueError) as exc:
        network._http_get("https://example.com/path")
    assert "host_not_allowed" in str(exc.value)


def test_http_get_allows_known_host(monkeypatch):
    captured = {}

    def fake_get(url, *, params=None, timeout=30):
        captured["url"] = url
        return DummyResp(json_data={"ok": True})

    monkeypatch.setattr(network, "STRICT_SECURITY", True)
    monkeypatch.setattr(network.SESSION, "get", fake_get)
    resp = network._http_get("https://query1.finance.yahoo.com/v8")
    assert resp.json()["ok"] is True
    assert captured["url"].startswith("https://query1.finance.yahoo.com")


def test_http_get_can_be_relaxed(monkeypatch):
    def fake_get(url, *, params=None, timeout=30):
        return DummyResp(json_data={"ok": True})

    monkeypatch.setattr(network, "STRICT_SECURITY", False)
    monkeypatch.setattr(network.SESSION, "get", fake_get)
    resp = network._http_get("https://example.com/data")
    assert resp.json()["ok"] is True


def test_fetch_feed_uses_secured_http(monkeypatch):
    rss = (
        "<rss version='2.0'><channel>"
        "<item><title>T1</title><link>https://example.com/1</link><description>Desc</description>"
        "<pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate></item>"
        "</channel></rss>"
    )

    captured = {}

    def fake_get(url, timeout=20):
        captured["url"] = url
        return DummyResp(text_data=rss)

    monkeypatch.setattr(data_sources, "_http_get", fake_get)
    items = data_sources._fetch_feed({"name": "Reuters", "url": "https://feeds.reuters.com/reuters/marketsNews"})
    assert captured["url"].startswith("https://feeds.reuters.com")
    assert items[0]["source"] == "Reuters"
