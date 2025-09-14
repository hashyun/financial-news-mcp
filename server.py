from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import feedparser
from dateutil import parser as dateparser

from finance_news import (
    app,
    _http_get,
    _normalize_article,
    _yahoo_options_chain,
    _fred_fetch,
    _dart_filings,
)


def _fetch_yahoo_chart(symbol: str, range_: str = "1mo", interval: str = "1d") -> Dict[str, Any]:
    base = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": range_, "interval": interval, "includePrePost": "false", "events": "div,splits"}
    r = _http_get(base, params=params, timeout=30)
    data = r.json()
    result = (data.get("chart", {}).get("result") or [None])[0]
    if not result:
        raise RuntimeError("no_data_for_symbol")
    ts = result.get("timestamp", []) or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes_arr = quote.get("close") or []
    vols = quote.get("volume") or []
    prices = []
    for i, t in enumerate(ts):
        dt = datetime.fromtimestamp(t, tz=timezone.utc).isoformat()
        prices.append(
            {
                "datetime": dt,
                "open": opens[i] if i < len(opens) else None,
                "high": highs[i] if i < len(highs) else None,
                "low": lows[i] if i < len(lows) else None,
                "close": closes_arr[i] if i < len(closes_arr) else None,
                "volume": vols[i] if i < len(vols) else None,
            }
        )
    closes = [p["close"] for p in prices if p["close"] is not None]
    change: Optional[float] = None
    if len(closes) >= 2 and closes[0]:
        change = (closes[-1] - closes[0]) / closes[0] * 100.0
    return {
        "symbol": symbol,
        "range": range_,
        "interval": interval,
        "points": prices,
        "summary": {
            "count": len(prices),
            "start_close": closes[0] if closes else None,
            "end_close": closes[-1] if closes else None,
            "pct_change": change,
        },
    }


def _google_news_rss(query: str, lang: str = "ko", region: str = "KR") -> List[Dict[str, Any]]:
    url = f"https://news.google.com/rss/search?q={query}&hl={lang}&gl={region}&ceid={region}:{lang}"
    r = _http_get(url, timeout=20)
    feed = feedparser.parse(r.text)
    out: List[Dict[str, Any]] = []
    for e in feed.entries:
        out.append(_normalize_article("GoogleNews", e))
    return out


__all__ = [
    "app",
    "_http_get",
    "_fetch_yahoo_chart",
    "_google_news_rss",
    "_normalize_article",
    "_yahoo_options_chain",
    "_fred_fetch",
    "_dart_filings",
]


if __name__ == "__main__":
    app.run()

