import pytest
import server
from types import SimpleNamespace
from dateutil import parser as dateparser
import finance_news.data_sources as data_sources


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
    monkeypatch.setattr(server, "_http_get", fake_get)
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
    monkeypatch.setattr(server, "_http_get", fake_get)
    items = server._google_news_rss("apple", lang="en", region="US")
    assert len(items) == 2
    assert items[0]["source"] == "GoogleNews"
    assert items[0]["title"] == "T1"
    assert items[1]["link"] == "http://ex/2"


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


def test_dart_filings(monkeypatch):
    data = {"status": "013", "list": []}

    def fake_get(url, *, params=None, timeout=30):
        return DummyResp(json_data=data)

    monkeypatch.setenv("DART_API_KEY", "key")
    monkeypatch.setattr(data_sources, "_http_get", fake_get)
    res = server._dart_filings(corp_code="12345678", page_count=5)
    assert res["status"] == "013"
