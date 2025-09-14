from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from finance_news import (
    _fetch_yahoo_chart,
    _google_news_rss,
    _news_all,
    COMMODITY_MAP,
    FX_ALIAS,
    INDEX_MAP,
    EQUITY_MAP,
)
from finance_news.data_sources import _normalize_kw

app = FastAPI(title="Financial News Web")


def _resolve_symbol(category: str, keyword: str) -> Optional[str]:
    maps = {
        "commodity": COMMODITY_MAP,
        "fx": FX_ALIAS,
        "index": INDEX_MAP,
        "equity": EQUITY_MAP,
    }
    m = maps.get(category.lower())
    if not m:
        return None
    return m.get(_normalize_kw(keyword))


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return (
        "<html><body><h1>Financial News</h1>"
        "<form action='/analyze' method='get'>"
        "<select name='category'>"
        "<option value='index'>지수</option>"
        "<option value='fx'>환율</option>"
        "<option value='commodity'>원자재</option>"
        "<option value='equity'>주식</option>"
        "</select>"
        "<input type='text' name='keyword' placeholder='Keyword'>"
        "<button type='submit'>Search</button>"
        "</form>"
        "<p>Quick Summaries:</p>"
        "<ul>"
        "<li><a href='/preset/kospi'>코스피</a></li>"
        "<li><a href='/preset/kosdaq'>코스닥</a></li>"
        "<li><a href='/preset/global'>글로벌</a></li>"
        "</ul>"
        "</body></html>"
    )


@app.get("/preset/{name}")
def preset(name: str, limit: int = 10) -> dict:
    n = name.lower()
    if n == "kospi":
        items = _google_news_rss("코스피")[:limit]
    elif n == "kosdaq":
        items = _google_news_rss("코스닥")[:limit]
    elif n == "global":
        items = _news_all()[:limit]
    else:
        raise HTTPException(status_code=404, detail="unknown_preset")
    return {"items": items}


@app.get("/analyze")
def analyze(category: str, keyword: str, limit: int = 10) -> dict:
    symbol = _resolve_symbol(category, keyword)
    chart = _fetch_yahoo_chart(symbol) if symbol else None
    news = _google_news_rss(keyword)[:limit]
    return {"symbol": symbol, "chart": chart, "news": news}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
