from fastapi.testclient import TestClient
import web.app as webapp


def test_preset_kospi(monkeypatch):
    def fake_news(query, lang="ko", region="KR"):
        assert query == "코스피"
        return [{"title": "t"}]
    monkeypatch.setattr(webapp, "_google_news_rss", fake_news)
    client = TestClient(webapp.app)
    resp = client.get("/preset/kospi")
    assert resp.status_code == 200
    assert resp.json()["items"][0]["title"] == "t"


def test_preset_global(monkeypatch):
    def fake_all():
        return [{"title": "g"}]
    monkeypatch.setattr(webapp, "_news_all", fake_all)
    client = TestClient(webapp.app)
    resp = client.get("/preset/global")
    assert resp.status_code == 200
    assert resp.json()["items"][0]["title"] == "g"


def test_analyze(monkeypatch):
    def fake_chart(symbol, range_="1mo", interval="1d"):
        return {"symbol": symbol}
    def fake_news(query, lang="ko", region="KR"):
        return [{"title": "n"}]
    monkeypatch.setattr(webapp, "_fetch_yahoo_chart", fake_chart)
    monkeypatch.setattr(webapp, "_google_news_rss", fake_news)
    client = TestClient(webapp.app)
    resp = client.get("/analyze", params={"category": "index", "keyword": "코스피"})
    data = resp.json()
    assert data["symbol"] == "^KS11"
    assert data["chart"]["symbol"] == "^KS11"
    assert data["news"][0]["title"] == "n"
