from __future__ import annotations

import os
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional, Literal, Dict, Any
import statistics
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP
from config import COMMODITY_MAP, FX_ALIAS, INDEX_MAP, EQUITY_MAP

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    def load_dotenv():
        return None

try:
    import requests_cache  # type: ignore
except Exception:  # pragma: no cover
    requests_cache = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("finance-mcp")


def _build_session() -> requests.Session:
    if requests_cache:
        try:
            requests_cache.install_cache("http_cache", expire_after=180)
            logger.info("requests-cache enabled (TTL=180s)")
        except Exception:
            pass
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET", "HEAD"]) 
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.headers.update({
        "User-Agent": "finnews-mcp/1.0 (+https://github.com/openai/codex-cli)",
        "Accept": "*/*",
    })
    return s


load_dotenv()
SESSION = _build_session()


def _http_get(url: str, *, params: Optional[dict] = None, timeout: int = 30) -> requests.Response:
    r = SESSION.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r


def _ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)


def _audit(tool: str, inputs: Dict[str, Any], result: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> None:
    try:
        _ensure_dir(os.path.join(BASE_DIR, "logs"))
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool": tool,
            "inputs": inputs,
            "ok": error is None,
            "error": error,
        }
        # keep result lightweight in audit
        if result is not None:
            rec["result_keys"] = list(result.keys())[:20]
        with open(os.path.join(BASE_DIR, "logs", "audit.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        logger.debug("audit logging failed", exc_info=True)



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
    prices = []
    for i, t in enumerate(ts):
        def _g(k):
            arr = quote.get(k) or []
            return arr[i] if i < len(arr) else None
        dt = datetime.fromtimestamp(t, tz=timezone.utc).isoformat()
        prices.append({"datetime": dt, "open": _g("open"), "high": _g("high"), "low": _g("low"), "close": _g("close"), "volume": _g("volume")})
    closes = [p["close"] for p in prices if p["close"] is not None]
    change = None
    if len(closes) >= 2 and closes[0]:
        change = (closes[-1] - closes[0]) / closes[0] * 100.0
    return {"symbol": symbol, "range": range_, "interval": interval, "points": prices, "summary": {"count": len(prices), "start_close": closes[0] if closes else None, "end_close": closes[-1] if closes else None, "pct_change": change}}


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


def _load_feeds() -> List[dict]:
    import yaml
    path = os.path.join(BASE_DIR, "feeds.yaml")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("sources", [])


def _normalize_article(source_name: str, entry: dict) -> dict:
    title = (entry.get("title") or "").strip()
    summary = _html_to_text(entry.get("summary") or entry.get("description") or "")
    link = entry.get("link") or ""
    published_dt = None
    for field in ("published", "updated", "pubDate"):
        if entry.get(field):
            try:
                published_dt = dateparser.parse(entry[field])
                break
            except Exception:
                continue
    if not published_dt:
        published_dt = datetime.now(timezone.utc)
    return {"source": source_name, "title": title, "summary": summary, "link": link, "published": published_dt.isoformat()}


def _google_news_rss(query: str, lang: str = "ko", region: str = "KR") -> List[dict]:
    base = "https://news.google.com/rss/search"
    params = {"q": query, "hl": f"{region.lower()}:{lang.lower()}", "gl": region.upper(), "ceid": f"{region.upper()}:{lang.lower()}"}
    r = _http_get(base, params=params, timeout=20)
    feed = feedparser.parse(r.text)
    out = []
    for e in feed.entries:
        out.append(_normalize_article("GoogleNews", e))
    return out


def _fetch_feed(source: dict) -> List[dict]:
    try:
        data = feedparser.parse(source.get("url"))
        entries = data.entries[:50]
        return [_normalize_article(source.get("name") or "", e) for e in entries]
    except Exception as e:
        logger.warning("feed error for %s: %s", source.get("name"), e)
        return []


def _news_all() -> List[dict]:
    sources = _load_feeds()
    if not sources:
        return []
    items: List[dict] = []
    with ThreadPoolExecutor(max_workers=min(8, max(2, len(sources)))) as ex:
        futs = {ex.submit(_fetch_feed, s): s for s in sources}
        for fut in as_completed(futs):
            items.extend(fut.result() or [])
    seen = set(); dedup: List[dict] = []
    for it in items:
        lk = it.get("link")
        if lk and lk not in seen:
            seen.add(lk); dedup.append(it)
    def _key(x: dict) -> float:
        try:
            return dateparser.parse(x.get("published") or "").timestamp()
        except Exception:
            return 0.0
    return sorted(dedup, key=_key, reverse=True)


def _artifact_markdown(title: str, lines: List[str]) -> dict:
    md = "\n".join([f"# {title}"] + lines)
    return {"kind": "markdown", "title": title, "content": md}


def _fred_fetch(args) -> dict:
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        return {"error": "missing_api_key", "env": "FRED_API_KEY"}
    base = "https://api.stlouisfed.org/fred/series/observations"
    out = {}
    for sid in args.series_ids:
        params: Dict[str, Any] = {"series_id": sid, "api_key": api_key, "file_type": "json"}
        if getattr(args, 'start', None):
            params["observation_start"] = args.start
        if getattr(args, 'end', None):
            params["observation_end"] = args.end
        if getattr(args, 'frequency', None):
            params["frequency"] = args.frequency
        if getattr(args, 'aggregation_method', None):
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
    for code in (getattr(args, 'item_code1', None), getattr(args, 'item_code2', None), getattr(args, 'item_code3', None)):
        if code is not None:
            url += f"/{code}"
    try:
        r = _http_get(url, timeout=30)
        return r.json()
    except Exception as e:
        return {"error": str(e), "url": url}


def _dart_filings(corp_name: Optional[str] = None, corp_code: Optional[str] = None,
                  bgn_de: Optional[str] = None, end_de: Optional[str] = None,
                  page_count: int = 10) -> dict:
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
        return {"error": "corp_identifier_required", "note": "Provide corp_code with DART_API_KEY, or corp_name for fallback"}
    results = _google_news_rss(f"site:dart.fss.or.kr {q}")
    return {"fallback": True, "items": results[:page_count]}


# ---------- Models ----------
class DiscoverArgs(BaseModel):
    category: str = Field("auto", description="'commodity'|'fx'|'index'|'equity'|'auto'")
    keyword: str = Field(..., description="Keyword (e.g., '커피', '달러원', '삼성전자')")
    limit: int = Field(5, ge=1, le=20, description="Max candidates")


class KeywordAnalyzeArgs(BaseModel):
    category: str = Field("auto")
    keyword: str = Field(...)
    range: str = Field("1mo")
    interval: str = Field("1d")


RangeLiteral = Literal['1d','5d','1mo','3mo','6mo','1y','2y','5y','10y','ytd','max']
IntervalLiteral = Literal['1m','2m','5m','15m','30m','60m','90m','1h','1d','5d','1wk','1mo','3mo']


class StockArgs(BaseModel):
    symbol: str = Field(...)
    range: RangeLiteral = Field("1mo")
    interval: IntervalLiteral = Field("1d")


class OptionsArgs(BaseModel):
    symbol: str = Field(...)
    expiration: Optional[str] = Field(None, description="YYYY-MM-DD (optional)")


class NewsArgs(BaseModel):
    keyword: Optional[str] = Field(None)
    lang: Optional[Literal['ko', 'en']] = Field(None)
    limit: int = Field(10, ge=1, le=100)


class RegNewsArgs(BaseModel):
    org: Literal['fss', 'fsc', 'all'] = Field('all')
    query: Optional[str] = None
    limit: int = Field(10, ge=1, le=50)


class FredArgs(BaseModel):
    series_ids: List[str]
    start: Optional[str] = None  # YYYY-MM-DD
    end: Optional[str] = None
    frequency: Optional[Literal['m', 'q', 'a']] = None
    aggregation_method: Optional[Literal['avg', 'sum', 'eop']] = None


class EcosArgs(BaseModel):
    stat_code: str
    start: str  # e.g., 201801
    end: str    # e.g., 202412
    cycle: Literal['M', 'Q', 'A'] = 'M'
    item_code1: Optional[str] = None
    item_code2: Optional[str] = None
    item_code3: Optional[str] = None


class RunMode(str, Enum):
    commodity = 'commodity'
    company = 'company'
    news = 'news'
    dart = 'dart'
    fred = 'fred'
    ecos = 'ecos'


class RunQueryArgs(BaseModel):
    mode: RunMode = Field(..., description="Select what to run")
    keyword: Optional[str] = Field(None, description="e.g., 커피 / 삼성전자 / 기축 통화")
    company_symbol: Optional[str] = Field(None, description="e.g., 005930.KS")
    range: RangeLiteral = Field("1mo")
    interval: IntervalLiteral = Field("1d")
    limit: int = Field(10, ge=1, le=100)


class WebAnalyzeRequest(BaseModel):
    category: str
    keyword: str
    range: str = "1mo"
    interval: str = "1d"


class MarketQuotesArgs(BaseModel):
    symbols: List[str]
    range: RangeLiteral = Field("1mo")
    interval: IntervalLiteral = Field("1d")


class MacroPresetArgs(BaseModel):
    preset: Optional[Literal['us_core', 'kr_core', 'global']] = None
    range: RangeLiteral = Field("1mo")
    interval: IntervalLiteral = Field("1d")
    groups: Optional[List[str]] = None
    fred_series: Optional[List[str]] = None
    fred_start: Optional[str] = None
    fred_end: Optional[str] = None
    include_ecos_kr_yield: Optional[bool] = False
    ecos_stat_code: Optional[str] = None
    ecos_cycle: Literal['M', 'Q', 'A'] = 'M'
    ecos_start: Optional[str] = None
    ecos_end: Optional[str] = None
    ecos_items: Optional[List[Dict[str, str]]] = None


class AnalyzeMarketsArgs(BaseModel):
    range: RangeLiteral = Field("1mo")
    interval: IntervalLiteral = Field("1d")
    equities: Optional[List[str]] = None
    include_vix: bool = False
    rates_source: Literal['fred', 'yahoo'] = 'yahoo'
    fred_series: Optional[List[str]] = None
    company_symbol: Optional[str] = None
    company_name: Optional[str] = None
    filings_days: Optional[int] = None
    include_fx: bool = False
    include_commodities: bool = False
    fx_symbols: Optional[List[str]] = None
    commodity_symbols: Optional[List[str]] = None


class AnalyzeCompanyArgs(BaseModel):
    company_symbol: str
    company_name: Optional[str] = None
    range: RangeLiteral = Field("1mo")
    interval: IntervalLiteral = Field("1d")
    news_limit: int = Field(10, ge=1, le=50)
    filings_days: Optional[int] = None
    include_regulator_news: bool = False


class MakeDigestArgs(BaseModel):
    keyword: Optional[str] = None
    lang: Optional[Literal['ko', 'en']] = None
    limit: int = Field(20, ge=1, le=100)


class PortfolioPosition(BaseModel):
    symbol: str
    weight: float


class PortfolioArgs(BaseModel):
    positions: List[PortfolioPosition]
    range: RangeLiteral = Field("1mo")
    interval: IntervalLiteral = Field("1d")


class QuickSummaryArgs(BaseModel):
    target: Literal['kr', 'us', 'global'] = 'global'
    range: RangeLiteral = Field("1mo")
    interval: IntervalLiteral = Field("1d")


class QuickCommodityArgs(BaseModel):
    preset: Optional[Literal['커피', 'WTI', '금', '구리', '은', '천연가스', '설탕', '옥수수', '코코아']] = None
    keyword: Optional[str] = None
    range: RangeLiteral = Field("1mo")
    interval: IntervalLiteral = Field("1d")


class QuickCompanyArgs(BaseModel):
    symbol: Optional[str] = None
    name: Optional[str] = None
    range: RangeLiteral = Field("1mo")
    interval: IntervalLiteral = Field("1d")


def discover_market(args: DiscoverArgs) -> dict:
    cat = (args.category or "auto").lower()
    kw = _normalize_kw(args.keyword)
    candidates: List[str] = []
    reason = ""

    if cat in ("commodity", "auto") and kw in COMMODITY_MAP:
        candidates.append(COMMODITY_MAP[kw]); reason = "commodity_map"
    if not candidates and cat in ("fx", "auto"):
        if kw in FX_ALIAS:
            candidates.append(FX_ALIAS[kw]); reason = reason or "fx_alias"
        elif len(kw) in (6, 7, 8) and kw.isalpha():
            if kw in FX_ALIAS:
                candidates.append(FX_ALIAS[kw]); reason = reason or "fx_pair"
    if not candidates and cat in ("index", "auto") and kw in INDEX_MAP:
        candidates.append(INDEX_MAP[kw]); reason = reason or "index_map"
    if not candidates and cat in ("equity", "auto"):
        if kw in EQUITY_MAP:
            candidates.append(EQUITY_MAP[kw]); reason = reason or "equity_map"
        elif any(s in kw for s in (".ks", ".kq")) or kw.startswith("^"):
            candidates.append(args.keyword); reason = reason or "pass_through"

    seen = set(); candidates = [c for c in candidates if not (c in seen or seen.add(c))][: args.limit]
    return {"category": cat, "keyword": args.keyword, "reason": reason, "candidates": candidates}


def analyze_keyword(args: KeywordAnalyzeArgs) -> dict:
    disc = discover_market(DiscoverArgs(category=args.category, keyword=args.keyword, limit=5))
    cands = disc.get("candidates") or []
    if not cands:
        return {"inputs": args.__dict__, "error": "no_symbol_found", "discover": disc, "warnings": ["No candidates"]}
    sym = cands[0]
    out = {"inputs": args.__dict__, "symbol": sym, "discover": disc, "chart": None, "narrative": "", "warnings": []}
    try:
        ch = _fetch_yahoo_chart(sym, args.range, args.interval)
        out["chart"] = ch
        closes = [p.get("close") for p in ch.get("points", []) if p.get("close") is not None]
        pct = None
        if len(closes) >= 2 and closes[0]:
            pct = (closes[-1] - closes[0]) / closes[0] * 100.0
        out["narrative"] = f"{sym} {args.range} {args.interval} 변동률: {pct:+.1f}%" if pct is not None else "변동률 계산 불가"
    except Exception as e:
        out["warnings"].append(str(e))
    return out


def _pct_change(points: List[dict]) -> Optional[float]:
    closes = [p.get("close") for p in points if p.get("close") is not None]
    if len(closes) >= 2 and closes[0]:
        return (closes[-1] - closes[0]) / closes[0] * 100.0
    return None


def _metrics(points: List[dict]) -> Dict[str, Any]:
    closes = [p.get("close") for p in points if p.get("close") is not None]
    if len(closes) < 2:
        return {"count": len(closes), "pct_change": None, "volatility": None, "max_drawdown": None}
    # simple returns
    rets = []
    peak = closes[0]
    max_dd = 0.0
    for i in range(1, len(closes)):
        c0, c1 = closes[i-1], closes[i]
        if c1 is None or c0 is None or c0 == 0:
            continue
        rets.append((c1 - c0) / c0)
        peak = max(peak, c1)
        dd = (c1 - peak) / peak if peak else 0.0
        max_dd = min(max_dd, dd)
    pct = (closes[-1] - closes[0]) / closes[0] * 100.0 if closes[0] else None
    vol = (statistics.pstdev(rets) * 100.0) if len(rets) >= 2 else None
    return {"count": len(closes), "pct_change": pct, "volatility": vol, "max_drawdown": max_dd * 100.0 if max_dd else 0.0}


app = FastMCP("finance-mcp")


@app.tool()
def ping() -> str:
    return "pong"


@app.tool()
def health() -> dict:
    keys = {k: bool(os.getenv(k)) for k in ("DART_API_KEY", "FRED_API_KEY", "BOK_API_KEY")}
    info = {
        "version": "1.0",
        "feeds": len(_load_feeds()),
        "api_keys": keys,
        "compliance_mode": bool(os.getenv("COMPLIANCE_MODE")),
        "cache_enabled": bool(os.getenv("REQUESTS_CACHE_BACKEND", "true")),
    }
    _audit("health", inputs={}, result=info)
    return info


@app.tool()
def list_sources() -> List[dict]:
    return _load_feeds()


@app.tool()
def get_news(args: NewsArgs) -> dict:
    try:
        items = _news_all()
        if getattr(args, 'keyword', None):
            kw = (args.keyword or '').lower()
            items = [x for x in items if kw in (x.get('title') or '').lower() or kw in (x.get('summary') or '').lower()]
        if getattr(args, 'lang', None):
            mapping = {s.get('name'): s.get('lang') for s in _load_feeds()}
            items = [x for x in items if mapping.get(x.get('source')) == args.lang]
        items = items[: args.limit]
        art = _artifact_markdown('뉴스', [f"- [{x['title']}]({x['link']})" for x in items]) if items else None
        out = {"items": items, "artifact": art}
        _audit("get_news", inputs=args.model_dump(), result=out)
        return out
    except Exception as e:
        _audit("get_news", inputs=args.model_dump(), error=str(e))
        return {"error": str(e)}


@app.tool()
def make_digest(args: MakeDigestArgs) -> dict:
    data = get_news(NewsArgs(keyword=args.keyword, lang=args.lang, limit=args.limit))
    items = data.get("items") or []
    if not items:
        return {"items": [], "artifact": _artifact_markdown("뉴스 다이제스트", ["- 최근 항목이 없습니다."])}
    lines = [f"- [{it['title']}]({it['link']})" for it in items]
    prompt = (
        "아래 최신 기사들을 바탕으로 간결한 한국어 요약을 작성하고, 시장 영향(지수/섹터/환율/원자재) 가능성을 항목별로 정리하세요."
    )
    art_lines = ["## 최근 뉴스"] + lines + ["", "## 제안 프롬프트", prompt]
    out = {"items": items, "artifact": _artifact_markdown("뉴스 다이제스트", art_lines)}
    _audit("make_digest", inputs=args.model_dump(), result=out)
    return out


@app.tool()
def regulator_news(args: RegNewsArgs) -> dict:
    queries = []
    user_q = (args.query or '').strip()
    if args.org in ('fss', 'all'):
        queries.append(f"site:fss.or.kr {user_q}".strip())
    if args.org in ('fsc', 'all'):
        queries.append(f"site:fsc.go.kr {user_q}".strip())
    all_items: List[dict] = []
    for q in queries:
        try:
            all_items.extend(_google_news_rss(q))
        except Exception:
            continue
    seen = set(); dedup: List[dict] = []
    for it in all_items:
        lk = it.get('link')
        if lk and lk not in seen:
            seen.add(lk); dedup.append(it)
    items = dedup[: args.limit]
    art = _artifact_markdown('감독/당국 소식', [f"- [{x['title']}]({x['link']})" for x in items]) if items else None
    out = {"items": items, "artifact": art}
    _audit("regulator_news", inputs=args.model_dump(), result=out)
    return out


@app.tool()
def stock_prices(args: StockArgs) -> dict:
    try:
        data = _fetch_yahoo_chart(args.symbol, args.range, args.interval)
        pct = _pct_change(data.get('points', []))
        m = _metrics(data.get('points', []))
        art = _artifact_markdown(
            f"{args.symbol} 가격({args.range}/{args.interval})",
            [
                f"- 데이터 포인트: {len(data.get('points', []))}",
                f"- 시작/종가: {data['summary']['start_close']} → {data['summary']['end_close']}",
                f"- 변동률: {pct:+.2f}%" if pct is not None else "- 변동률: N/A",
                f"- 변동성(표준편차): {m['volatility']:.2f}%" if m.get('volatility') is not None else "- 변동성: N/A",
                f"- 최대낙폭: {m['max_drawdown']:.2f}%",
            ],
        )
        out = {"chart": data, "metrics": m, "artifact": art}
        _audit("stock_prices", inputs=args.model_dump(), result=out)
        return out
    except Exception as e:
        _audit("stock_prices", inputs=args.model_dump(), error=str(e))
        return {"error": str(e)}


@app.tool()
def options_chain(args: OptionsArgs) -> dict:
    return _yahoo_options_chain(args.symbol, args.expiration)


@app.tool()
def market_quotes(args: MarketQuotesArgs) -> dict:
    try:
        syms = list(dict.fromkeys(args.symbols))[:50]
        results: List[dict] = []
        errors: Dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=min(8, max(2, len(syms)))) as ex:
            futs = {ex.submit(_fetch_yahoo_chart, s, args.range, args.interval): s for s in syms}
            for fut in as_completed(futs):
                sym = futs[fut]
                try:
                    results.append(fut.result())
                except Exception as e:
                    errors[sym] = str(e)
        summary = {r["symbol"]: r.get("summary", {}) for r in results}
        out = {"range": args.range, "interval": args.interval, "quotes": results, "errors": errors, "summary": summary}
        _audit("market_quotes", inputs=args.model_dump(), result=out)
        return out
    except Exception as e:
        _audit("market_quotes", inputs=args.model_dump(), error=str(e))
        return {"error": str(e)}


@app.tool()
def fred_series(args: FredArgs) -> dict:
    out = _fred_fetch(args)
    _audit("fred_series", inputs=args.model_dump(), result=out if isinstance(out, dict) else None)
    return out


@app.tool()
def bok_series(args: EcosArgs) -> dict:
    out = _ecos_fetch(args)
    _audit("bok_series", inputs=args.model_dump(), result=out if isinstance(out, dict) else None)
    return out


@app.tool()
def macro_preset(args: MacroPresetArgs) -> dict:
    presets = {
        "us_core": {
            "symbols": ["^GSPC", "^NDX", "^TNX", "KRW=X", "EURUSD=X", "CL=F", "GC=F", "NG=F", "^VIX"],
            "fred": ["DGS10", "CPIAUCSL", "UNRATE"],
        },
        "kr_core": {
            "symbols": ["^KS11", "KRW=X", "^TNX", "CL=F", "GC=F", "^VIX"],
            "fred": ["DGS10"],
        },
        "global": {
            "symbols": ["^GSPC", "^KS11", "KRW=X", "EURUSD=X", "CL=F", "GC=F", "NG=F", "^VIX"],
            "fred": ["DGS10", "CPIAUCSL", "UNRATE"],
        },
    }
    chosen = presets.get(args.preset or "us_core")
    symbols = chosen["symbols"]
    if args.groups:
        symbols = chosen["symbols"]
    mq = market_quotes(MarketQuotesArgs(symbols=symbols, range=args.range, interval=args.interval))

    fred_ids = args.fred_series or chosen.get("fred", [])
    fred = fred_series(FredArgs(series_ids=fred_ids, start=args.fred_start, end=args.fred_end)) if fred_ids else {}

    ecos = None
    if args.include_ecos_kr_yield and args.ecos_stat_code and args.ecos_start and args.ecos_end:
        ecos = _ecos_fetch(EcosArgs(
            stat_code=args.ecos_stat_code,
            start=args.ecos_start,
            end=args.ecos_end,
            cycle=args.ecos_cycle or 'M',
            item_code1=None,
        ))

    title = f"매크로 프리셋 ({args.preset or 'us_core'})"
    lines = [f"- 범위: {args.range}/{args.interval}", f"- 심볼: {', '.join(symbols)}"]
    art = _artifact_markdown(title, lines)
    out = {"quotes": mq, "fred": fred, "ecos": ecos, "artifact": art}
    _audit("macro_preset", inputs=args.model_dump(), result=out)
    return out


@app.tool()
def dart_filings(corp_name: Optional[str] = None, corp_code: Optional[str] = None,
                 bgn_de: Optional[str] = None, end_de: Optional[str] = None,
                 page_count: int = 10) -> dict:
    out = _dart_filings(corp_name=corp_name, corp_code=corp_code, bgn_de=bgn_de, end_de=end_de, page_count=page_count)
    _audit("dart_filings", inputs={"corp_name": corp_name, "corp_code": corp_code, "bgn_de": bgn_de, "end_de": end_de, "page_count": page_count}, result=out if isinstance(out, dict) else None)
    return out


@app.tool()
def analyze_markets(args: AnalyzeMarketsArgs) -> dict:
    equities = args.equities or ["^GSPC", "^KS11"]
    symbols = list(equities)
    if args.include_vix:
        symbols.append("^VIX")
    if args.include_fx:
        symbols.extend(args.fx_symbols or ["KRW=X", "EURUSD=X"])
    if args.include_commodities:
        symbols.extend(args.commodity_symbols or ["CL=F", "GC=F"])
    mq = market_quotes(MarketQuotesArgs(symbols=symbols, range=args.range, interval=args.interval))

    rates_info: Dict[str, Any] = {}
    if args.rates_source == 'yahoo':
        try:
            tn = _fetch_yahoo_chart("^TNX", args.range, args.interval)
            rates_info = {"^TNX": tn.get("summary")}
        except Exception as e:
            rates_info = {"error": str(e)}
    else:
        ids = args.fred_series or ["DGS10"]
        rates_info = fred_series(FredArgs(series_ids=ids))

    def _fmt(sym: str, summ: Dict[str, Any]) -> str:
        pct = summ.get("pct_change")
        if pct is None:
            return f"{sym}: N/A"
        return f"{sym}: {pct:+.1f}%"

    lines = ["시장 요약"]
    for sym in equities:
        summ = mq.get("summary", {}).get(sym, {})
        lines.append(f"- {_fmt(sym, summ)}")
    if args.include_vix:
        summ = mq.get("summary", {}).get("^VIX", {})
        lines.append(f"- 변동성(VIX): {_fmt('^VIX', summ)}")
    if args.include_fx:
        for s in (args.fx_symbols or ["KRW=X", "EURUSD=X"]):
            summ = mq.get("summary", {}).get(s, {})
            lines.append(f"- FX {s}: {_fmt(s, summ)}")
    if args.include_commodities:
        for s in (args.commodity_symbols or ["CL=F", "GC=F"]):
            summ = mq.get("summary", {}).get(s, {})
            lines.append(f"- 원자재 {s}: {_fmt(s, summ)}")

    art = _artifact_markdown("시장 해설", lines)
    out = {"quotes": mq, "rates": rates_info, "artifact": art}
    _audit("analyze_markets", inputs=args.model_dump(), result=out)
    return out


@app.tool()
def analyze_company(args: AnalyzeCompanyArgs) -> dict:
    out: Dict[str, Any] = {"inputs": args.dict()}
    try:
        chart = _fetch_yahoo_chart(args.company_symbol, args.range, args.interval)
        out["chart"] = chart
    except Exception as e:
        out.setdefault("warnings", []).append(f"chart_error: {e}")

    kw = args.company_name or args.company_symbol
    news = get_news(NewsArgs(keyword=kw, limit=args.news_limit))
    out["news"] = news

    filings = _dart_filings(corp_name=args.company_name or None, page_count=min(20, args.news_limit))
    out["filings"] = filings

    if args.include_regulator_news and args.company_name:
        reg = regulator_news(RegNewsArgs(org='all', query=args.company_name, limit=10))
        out["regulator"] = reg

    pct = None
    if out.get("chart"):
        pts = out["chart"].get("points", [])
        closes = [p.get("close") for p in pts if p.get("close") is not None]
        if len(closes) >= 2 and closes[0]:
            pct = (closes[-1] - closes[0]) / closes[0] * 100.0
    title = f"기업 분석: {args.company_symbol}" + (f" ({args.company_name})" if args.company_name else "")
    lines = [
        f"- 기간: {args.range}/{args.interval}",
        f"- 수익률: {pct:+.2f}%" if pct is not None else "- 수익률: N/A",
        f"- 뉴스 항목: {len(news.get('items') or [])}",
    ]
    out["artifact"] = _artifact_markdown(title, lines)
    _audit("analyze_company", inputs=args.model_dump(), result=out)
    return out


@app.tool()
def portfolio_snapshot(args: PortfolioArgs) -> dict:
    positions = args.positions
    if not positions:
        return {"error": "no_positions"}
    # normalize weights
    wsum = sum(p.weight for p in positions)
    if wsum == 0:
        return {"error": "zero_weight"}
    norm_pos = [(p.symbol, p.weight / wsum) for p in positions]
    # fetch series
    series: Dict[str, List[dict]] = {}
    for sym, _w in norm_pos:
        try:
            data = _fetch_yahoo_chart(sym, args.range, args.interval)
            series[sym] = data.get("points", [])
        except Exception:
            series[sym] = []
    # align by index length (use min length)
    min_len = min((len(v) for v in series.values() if v), default=0)
    if min_len == 0:
        return {"error": "no_data"}
    # build portfolio close path
    port_closes: List[float] = []
    for i in range(min_len):
        total = 0.0
        for sym, w in norm_pos:
            pt = series[sym][i]
            c = pt.get("close")
            if c is None:
                break
            total += w * c
        else:
            port_closes.append(total)
            continue
        # missing close for some symbol -> stop
        break
    # convert to points-like for metrics
    points = [{"close": c} for c in port_closes]
    m = _metrics(points)
    title = "포트폴리오 스냅샷"
    lines = [
        f"- 범위: {args.range}/{args.interval}",
        f"- 종목: {', '.join([f'{s}({w:.0%})' for s, w in norm_pos])}",
        f"- 수익률: {m['pct_change']:+.2f}%" if m.get('pct_change') is not None else "- 수익률: N/A",
        f"- 변동성: {m['volatility']:.2f}%" if m.get('volatility') is not None else "- 변동성: N/A",
        f"- 최대낙폭: {m['max_drawdown']:.2f}%",
    ]
    out = {"positions": [p.model_dump() for p in positions], "metrics": m, "artifact": _artifact_markdown(title, lines)}
    _audit("portfolio_snapshot", inputs=args.model_dump(), result=out)
    return out


@app.tool()
def quick_summary(args: QuickSummaryArgs) -> dict:
    if args.target == 'kr':
        return analyze_markets(AnalyzeMarketsArgs(range=args.range, interval=args.interval, equities=["^KS11"], include_vix=True, include_fx=True, include_commodities=True))
    if args.target == 'us':
        return analyze_markets(AnalyzeMarketsArgs(range=args.range, interval=args.interval, equities=["^GSPC", "^NDX"], include_vix=True, include_fx=True, include_commodities=True))
    return analyze_markets(AnalyzeMarketsArgs(range=args.range, interval=args.interval, equities=["^GSPC", "^KS11"], include_vix=True, include_fx=True, include_commodities=True))


@app.tool()
def quick_commodity(args: QuickCommodityArgs) -> dict:
    kw = (args.keyword or '').strip()
    if not kw and args.preset:
        preset_map = {
            '커피': '커피', 'WTI': 'wti', '금': '금', '구리': '구리', '은': '은', '천연가스': '천연가스', '설탕': '설탕', '옥수수': '옥수수', '코코아': '코코아'
        }
        kw = preset_map.get(args.preset) or args.preset
    if not kw:
        return {"error": "keyword_required", "hint": "preset 또는 keyword를 설정하세요"}
    return analyze_keyword(KeywordAnalyzeArgs(category="commodity", keyword=kw, range=args.range, interval=args.interval))


@app.tool()
def quick_company(args: QuickCompanyArgs) -> dict:
    sym = (args.symbol or '').strip() or None
    name = (args.name or '').strip() or None
    if not sym and name:
        disc = discover_market(DiscoverArgs(category='equity', keyword=name, limit=5))
        cands = disc.get('candidates') or []
        sym = cands[0] if cands else None
    if not sym:
        return {"error": "no_symbol", "hint": "symbol 또는 name을 지정하세요"}
    return analyze_company(AnalyzeCompanyArgs(company_symbol=sym, company_name=name or None, range=args.range, interval=args.interval))


@app.tool()
def ui_menu() -> dict:
    lines = [
        "## 빠른 요약",
        "- quick_summary { target: 'kr'|'us'|'global', range: '1mo', interval: '1d' }",
        "",
        "## 원자재",
        "- quick_commodity { preset: '커피'|'WTI'|'금'|'구리'|'은'|'천연가스'|'설탕'|'옥수수'|'코코아' }",
        "- 또는 quick_commodity { keyword: '커피' }",
        "",
        "## 개별 기업",
        "- quick_company { name: '삼성전자', range: '1mo' }",
        "- 또는 quick_company { symbol: '005930.KS' }",
        "",
        "## 자유 검색",
        "- discover_market { category: 'commodity'|'fx'|'index'|'equity'|'auto', keyword: '커피' }",
    ]
    return {"artifact": _artifact_markdown("MCP UI 메뉴", lines)}


# --- One-click preset tools for MCP clients without dropdowns ---
@app.tool()
def summary_kr(range: RangeLiteral = "1mo", interval: IntervalLiteral = "1d") -> dict:
    return analyze_markets(AnalyzeMarketsArgs(range=range, interval=interval, equities=["^KS11"], include_vix=True, include_fx=True, include_commodities=True))


@app.tool()
def summary_us(range: RangeLiteral = "1mo", interval: IntervalLiteral = "1d") -> dict:
    return analyze_markets(AnalyzeMarketsArgs(range=range, interval=interval, equities=["^GSPC", "^NDX"], include_vix=True, include_fx=True, include_commodities=True))


@app.tool()
def summary_global(range: RangeLiteral = "1mo", interval: IntervalLiteral = "1d") -> dict:
    return analyze_markets(AnalyzeMarketsArgs(range=range, interval=interval, equities=["^GSPC", "^KS11"], include_vix=True, include_fx=True, include_commodities=True))


@app.tool()
def commodity_coffee(range: RangeLiteral = "1mo", interval: IntervalLiteral = "1d") -> dict:
    return analyze_keyword(KeywordAnalyzeArgs(category="commodity", keyword="커피", range=range, interval=interval))


@app.tool()
def commodity_wti(range: RangeLiteral = "1mo", interval: IntervalLiteral = "1d") -> dict:
    return analyze_keyword(KeywordAnalyzeArgs(category="commodity", keyword="wti", range=range, interval=interval))


@app.tool()
def commodity_gold(range: RangeLiteral = "1mo", interval: IntervalLiteral = "1d") -> dict:
    return analyze_keyword(KeywordAnalyzeArgs(category="commodity", keyword="금", range=range, interval=interval))


@app.tool()
def commodity_copper(range: RangeLiteral = "1mo", interval: IntervalLiteral = "1d") -> dict:
    return analyze_keyword(KeywordAnalyzeArgs(category="commodity", keyword="구리", range=range, interval=interval))


# Zero-argument wrappers for button-like UX in clients that don't render dropdowns
@app.tool()
def go_kr() -> dict:
    return analyze_markets(AnalyzeMarketsArgs(range="1mo", interval="1d", equities=["^KS11"], include_vix=True, include_fx=True, include_commodities=True))


@app.tool()
def go_us() -> dict:
    return analyze_markets(AnalyzeMarketsArgs(range="1mo", interval="1d", equities=["^GSPC", "^NDX"], include_vix=True, include_fx=True, include_commodities=True))


@app.tool()
def go_global() -> dict:
    return analyze_markets(AnalyzeMarketsArgs(range="1mo", interval="1d", equities=["^GSPC", "^KS11"], include_vix=True, include_fx=True, include_commodities=True))


@app.tool()
def go_coffee() -> dict:
    return analyze_keyword(KeywordAnalyzeArgs(category="commodity", keyword="커피", range="1mo", interval="1d"))


@app.tool()
def go_wti() -> dict:
    return analyze_keyword(KeywordAnalyzeArgs(category="commodity", keyword="wti", range="1mo", interval="1d"))


@app.tool()
def go_gold() -> dict:
    return analyze_keyword(KeywordAnalyzeArgs(category="commodity", keyword="금", range="1mo", interval="1d"))


@app.tool()
def go_copper() -> dict:
    return analyze_keyword(KeywordAnalyzeArgs(category="commodity", keyword="구리", range="1mo", interval="1d"))


@app.tool()
def run_query(args: RunQueryArgs) -> dict:
    mode = args.mode.value if isinstance(args.mode, Enum) else str(args.mode)
    if mode == 'commodity':
        disc = discover_market(DiscoverArgs(category='commodity', keyword=args.keyword or '', limit=5))
        cands = disc.get('candidates') or []
        if not cands:
            return {"error": "no_symbol", "discover": disc}
        sym = cands[0]
        chart = _fetch_yahoo_chart(sym, args.range, args.interval)
        art = _artifact_markdown("원자재 차트", [f"- {args.keyword} → {sym}", f"- 기간: {args.range}/{args.interval}"])
        out = {"mode": mode, "keyword": args.keyword, "symbol": sym, "chart": chart, "artifact": art}
        _audit("run_query", inputs=args.model_dump(), result=out)
        return out
    if mode == 'company':
        sym = args.company_symbol
        if not sym and args.keyword:
            k = _normalize_kw(args.keyword)
            sym = EQUITY_MAP.get(k)
            if not sym:
                disc = discover_market(DiscoverArgs(category='equity', keyword=args.keyword, limit=5))
                cands = disc.get('candidates') or []
                sym = cands[0] if cands else None
        if not sym:
            return {"error": "no_company_symbol", "hint": "Set company_symbol or a known keyword"}
        chart = _fetch_yahoo_chart(sym, args.range, args.interval)
        art = _artifact_markdown("기업 차트", [f"- 종목: {sym}", f"- 기간: {args.range}/{args.interval}"])
        out = {"mode": mode, "company_symbol": sym, "chart": chart, "artifact": art}
        _audit("run_query", inputs=args.model_dump(), result=out)
        return out
    if mode == 'news':
        news = get_news(NewsArgs(keyword=args.keyword, limit=args.limit))
        out = {"mode": mode, **news}
        _audit("run_query", inputs=args.model_dump(), result=out)
        return out
    if mode == 'dart':
        filings = _dart_filings(corp_name=args.keyword, page_count=args.limit)
        title = f"DART 공시 ({args.keyword})" if args.keyword else "DART 공시"
        lines = []
        items = filings.get('items') or filings.get('list') or []
        for it in items[: args.limit]:
            t = it.get('title') or it.get('report_nm') or ''
            l = it.get('link') or ''
            if t and l:
                lines.append(f"- [{t}]({l})")
        art = _artifact_markdown(title, lines) if lines else None
        out = {"mode": mode, "filings": filings, "artifact": art}
        _audit("run_query", inputs=args.model_dump(), result=out)
        return out
    if mode == 'fred':
        if not args.keyword:
            return {"error": "keyword_required", "hint": "Comma-separated FRED series IDs"}
        ids = [x.strip() for x in (args.keyword or '').split(',') if x.strip()]
        data = _fred_fetch(FredArgs(series_ids=ids))
        art = _artifact_markdown("FRED 시계열", [f"- {', '.join(ids)}"])
        out = {"mode": mode, "series": data, "artifact": art}
        _audit("run_query", inputs=args.model_dump(), result=out)
        return out
    if mode == 'ecos':
        if not args.keyword:
            return {"error": "keyword_required", "hint": "STAT_CODE [ITEM_CODE1 [ITEM_CODE2 [ITEM_CODE3]]]"}
        parts = (args.keyword or '').split()
        stat = parts[0]
        item1 = parts[1] if len(parts) > 1 else None
        item2 = parts[2] if len(parts) > 2 else None
        item3 = parts[3] if len(parts) > 3 else None
        data = _ecos_fetch(EcosArgs(stat_code=stat, start='201801', end='202512', item_code1=item1, item_code2=item2, item_code3=item3))
        art = _artifact_markdown("ECOS 시계열", [f"- {stat} {item1 or ''} {item2 or ''} {item3 or ''}".strip()])
        out = {"mode": mode, "series": data, "artifact": art}
        _audit("run_query", inputs=args.model_dump(), result=out)
        return out
    out = {"error": "unsupported_mode", "mode": mode}
    _audit("run_query", inputs=args.model_dump(), result=out)
    return out


@app.tool()
def discover_market_tool(args: DiscoverArgs) -> dict:
    return discover_market(args)


@app.tool()
def analyze_keyword_tool(args: KeywordAnalyzeArgs) -> dict:
    return analyze_keyword(args)


if __name__ == "__main__":
    logger.info("MCP 서버 시작")
    app.run()
