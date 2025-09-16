from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional

import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from .network import _http_get


def _lower_keys(d: Dict[str, str]) -> Dict[str, str]:
    return {(k or "").strip().lower(): v for k, v in d.items()}


COMMODITY_MAP = _lower_keys({
    "coffee": "KC=F", "\ucf54\ud53c": "KC=F",
    "wti": "CL=F", "oil": "CL=F", "\uc6d0\uc720": "CL=F",
    "brent": "BZ=F", "\ube0c\ub80c\ud2b8": "BZ=F", "\ube0c\ub80c\ud2b8\uc720": "BZ=F",
    "gold": "GC=F", "\uae08": "GC=F",
    "silver": "SI=F", "\uc740": "SI=F",
    "copper": "HG=F", "\uad6c\ub9ac": "HG=F",
    "natgas": "NG=F", "lng": "NG=F", "\ucc9c\uc5f0\uac00\uc2a4": "NG=F",
    "gasoline": "RB=F", "\ud718\ubc1c\uc720": "RB=F",
    "corn": "ZC=F", "\uc625\uc218\uc218": "ZC=F",
    "soybean": "ZS=F", "\ub300\ub450": "ZS=F",
    "wheat": "ZW=F", "\ubc00": "ZW=F",
    "sugar": "SB=F", "\uc124\ud0d5": "SB=F",
    "cocoa": "CC=F", "\ucf54\ucf54\uc544": "CC=F",
})

FX_ALIAS = _lower_keys({
    "dxy": "DX=F", "\ub2ec\ub7ec\uc9c0\uc218": "DX=F", "\ub2ec\ub7ec\uc778\ub371\uc2a4": "DX=F",
    "eurusd": "EURUSD=X", "\uc720\ub85c\ub2ec\ub7ec": "EURUSD=X", "\uc720\ub85c/\ub2ec\ub7ec": "EURUSD=X",
    "usdjpy": "JPY=X", "\ub2ec\ub7ec\uc5d4": "JPY=X", "\uc5d4\ud654": "JPY=X",
    "usdkrw": "KRW=X", "\ub2ec\ub7ec\uc6d0": "KRW=X", "\ub2ec\ub7ec/\uc6d0": "KRW=X", "\uc6d0\ud654": "KRW=X", "krw": "KRW=X",
})

INDEX_MAP = _lower_keys({
    "s&p": "^GSPC", "spx": "^GSPC", "s&p500": "^GSPC", "sp500": "^GSPC",
    "nasdaq100": "^NDX", "ndx": "^NDX", "\ub098\uc2a4\ub2e4\uadf8100": "^NDX",
    "dow": "^DJI", "djia": "^DJI", "\ub2e4\uc6b0": "^DJI",
    "kospi": "^KS11", "\ucf54\uc2a4\ud53c": "^KS11",
    "kospi200": "^KS200", "\ucf54\uc2a4\ud53c200": "^KS200",
    "vix": "^VIX",
})

EQUITY_MAP: Dict[str, str] = _lower_keys({
    "\uc0bc\uc131\uc804\uc790": "005930.KS",
    "\uc0bc\uc131\uc804\uc790\uc6b0": "005935.KS",
    "\ud604\ub300\ucc28": "005380.KS",
    "lg\uc5d0\ub108\uc9c0\uc194\ub8e8\uc158": "373220.KS",
    "\ub124\uc774\ubc84": "035420.KS",
    "\uce74\uce74\uc624": "035720.KS",
    "sk\ud558\uc774\ub2c8\uc2a4": "000660.KS",
    "apple": "AAPL",
    "tesla": "TSLA",
    "microsoft": "MSFT",
})


def _normalize_kw(s: str) -> str:
    return (s or "").strip().lower()


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(" ")
    return " ".join(text.split())


def _fetch_yahoo_chart(symbol: str, range_: str = "1mo", interval: str = "1d") -> dict:
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
        prices.append({
            "datetime": dt,
            "open": opens[i] if i < len(opens) else None,
            "high": highs[i] if i < len(highs) else None,
            "low": lows[i] if i < len(lows) else None,
            "close": closes_arr[i] if i < len(closes_arr) else None,
            "volume": vols[i] if i < len(vols) else None,
        })
    closes = [p["close"] for p in prices if p["close"] is not None]
    change = None
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


def _yahoo_options_chain(symbol: str, expiration: Optional[str] = None) -> dict:
    base = f"https://query2.finance.yahoo.com/v7/finance/options/{symbol}"
    params: Dict[str, Any] = {}
    if expiration:
        try:
            dt = dateparser.parse(expiration)
            params["date"] = int(dt.timestamp())
        except Exception:
            pass
    r = _http_get(base, params=params, timeout=30)
    return r.json()


@lru_cache()
def _load_feeds() -> List[dict]:
    import yaml

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "feeds.yaml")
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("sources", [])


def _normalize_article(source_name: str, entry: dict) -> dict:
    title = (entry.get("title") or "").strip()
    if not title:
        return {}
    link = entry.get("link") or ""
    published = entry.get("published") or entry.get("pubDate") or ""
    try:
        pdt = dateparser.parse(published)
        published = pdt.isoformat() if pdt else ""
    except Exception:
        published = ""
    desc = _html_to_text(entry.get("summary") or entry.get("description") or "")
    return {"source": source_name, "title": title, "link": link, "published": published, "summary": desc}


def _google_news_rss(query: str, lang: str = "ko", region: str = "KR") -> List[dict]:
    url = f"https://news.google.com/rss/search?q={query}&hl={lang}&gl={region}&ceid={region}:{lang}"
    try:
        r = _http_get(url, timeout=20)
        feed = feedparser.parse(r.text)
    except Exception:
        return []
    out: List[dict] = []
    for e in feed.entries:
        out.append(_normalize_article("Google News", e))
    return out


def _fetch_feed(source: dict) -> List[dict]:
    url = source.get("url")
    name = source.get("name") or url
    if not url:
        return []
    try:
        resp = _http_get(url, timeout=20)
        feed = feedparser.parse(resp.text)
    except Exception:
        return []
    items: List[dict] = []
    for entry in feed.entries:
        it = _normalize_article(name, entry)
        if it:
            items.append(it)
    return items


def _news_all() -> List[dict]:
    sources = _load_feeds()
    if not sources:
        return []
    items: List[dict] = []
    with ThreadPoolExecutor(max_workers=min(8, max(2, len(sources)))) as ex:
        futs = {ex.submit(_fetch_feed, s): s for s in sources}
        for fut in as_completed(futs):
            items.extend(fut.result() or [])
    seen = set()
    dedup: List[dict] = []
    for it in items:
        lk = it.get("link")
        if lk and lk not in seen:
            seen.add(lk)
            dedup.append(it)
    def _key(x: dict) -> float:
        try:
            return dateparser.parse(x.get("published") or "").timestamp()
        except Exception:
            return 0.0
    return sorted(dedup, key=_key, reverse=True)


def _fred_fetch(args) -> dict:
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        return {"error": "missing_api_key", "env": "FRED_API_KEY"}
    base = "https://api.stlouisfed.org/fred/series/observations"
    out = {}
    for sid in args.series_ids:
        params: Dict[str, Any] = {"series_id": sid, "api_key": api_key, "file_type": "json"}
        if getattr(args, "start", None):
            params["observation_start"] = args.start
        if getattr(args, "end", None):
            params["observation_end"] = args.end
        if getattr(args, "frequency", None):
            params["frequency"] = args.frequency
        if getattr(args, "aggregation_method", None):
            params["aggregation_method"] = args.aggregation_method
        try:
            r = _http_get(base, params=params, timeout=30)
            out[sid] = r.json()
        except Exception as e:
            out[sid] = {"error": str(e)}
    return out


def _ecos_fetch(args) -> dict:
    api_key = os.getenv("BOK_API_KEY")
    if not api_key:
        return {"error": "missing_api_key", "env": "BOK_API_KEY"}
    base = "https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/10000/{stat}/{start}/{end}/{cycle}"
    url = base.format(key=api_key, stat=args.stat_code, start=args.start, end=args.end, cycle=args.cycle)
    for code in (
        getattr(args, "item_code1", None),
        getattr(args, "item_code2", None),
        getattr(args, "item_code3", None),
    ):
        if code is not None:
            url += f"/{code}"
    try:
        r = _http_get(url, timeout=30)
        return r.json()
    except Exception as e:
        return {"error": str(e), "url": url}


def _dart_filings(
    corp_name: Optional[str] = None,
    corp_code: Optional[str] = None,
    bgn_de: Optional[str] = None,
    end_de: Optional[str] = None,
    page_count: int = 10,
) -> dict:
    api_key = os.getenv("DART_API_KEY")
    if api_key and corp_code:
        base = "https://opendart.fss.or.kr/api/list.json"
        params: Dict[str, Any] = {"crtfc_key": api_key, "corp_code": corp_code, "page_count": page_count}
        if bgn_de:
            params["bgn_de"] = bgn_de
        if end_de:
            params["end_de"] = end_de
        try:
            r = _http_get(base, params=params, timeout=30)
            return r.json()
        except Exception as e:
            return {"error": str(e)}
    q = (corp_name or "").strip()
    if not q:
        return {
            "error": "corp_identifier_required",
            "note": "Provide corp_code with DART_API_KEY, or corp_name for fallback",
        }
    results = _google_news_rss(f"site:dart.fss.or.kr {q}")
    return {"fallback": True, "items": results[:page_count]}


__all__ = [
    "COMMODITY_MAP",
    "FX_ALIAS",
    "INDEX_MAP",
    "EQUITY_MAP",
    "_normalize_kw",
    "_html_to_text",
    "_fetch_yahoo_chart",
    "_yahoo_options_chain",
    "_load_feeds",
    "_normalize_article",
    "_google_news_rss",
    "_fetch_feed",
    "_news_all",
    "_fred_fetch",
    "_ecos_fetch",
    "_dart_filings",
]
