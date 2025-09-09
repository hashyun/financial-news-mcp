# Finance News MCP

MCP server exposing finance/news tools: RSS aggregation, Yahoo Finance charts, FRED/ECOS macro, and OpenDART filings.

## Run
1. Create/activate a Python virtualenv
2. Install deps
   ```powershell
   pip install -r requirements.txt
   ```
3. (Optional) Set API keys via env or .env
   - PowerShell: `setx DART_API_KEY "<YOUR_KEY>"`; `setx FRED_API_KEY "<YOUR_KEY>"`; `setx BOK_API_KEY "<YOUR_KEY>"`
   - macOS/Linux: `export DART_API_KEY="<YOUR_KEY>"` (and others). Or create a `.env` file with `KEY=VALUE` lines.
4. Start server
   ```powershell
   python server.py
   ```

### Web UI (optional)
- Start the web server:
  ```powershell
  python web/app.py
  ```
- Open http://127.0.0.1:8000 in your browser.
- Click preset buttons (코스피, 코스닥, 글로벌) for quick summaries, or use the category + keyword search to analyze a specific market (e.g., 커피/환율/삼성전자).

Notes:
- The server uses retries and short-lived caching (requests-cache, ~180s) for resilience.
- RSS sources are configured in `feeds.yaml`.

## Tools
- ping: Health check
- health: Environment/keys/feed counts; compliance mode flag; cache on/off
- list_sources: List configured RSS feeds from `feeds.yaml`
- get_news: Fetch + filter from configured RSS feeds
- make_digest: Latest items bundle + suggested prompt
- run_query: Guided category flow (`commodity`|`company`|`news`|`dart`|`fred`|`ecos`)
  - Args: `{ mode: 'commodity'|'company'|'news'|'dart'|'fred'|'ecos', keyword?: string, company_symbol?: string, range?: string, interval?: string, limit?: number }`
  - Examples:
    - `run_query { mode: 'commodity', keyword: '커피', range: '1mo', interval: '1d' }` → KC=F
    - `run_query { mode: 'company', keyword: '삼성전자', range: '1mo' }` → 005930.KS
    - `run_query { mode: 'news', keyword: '반도체', limit: 10 }`
    - `run_query { mode: 'dart', keyword: '삼성전자', limit: 10 }`
    - `run_query { mode: 'fred', keyword: 'DGS10,CPIAUCSL' }`
    - `run_query { mode: 'ecos', keyword: 'STAT_CODE ITEM1', }`
- regulator_news: FSS/FSC press/news via Google News RSS
  - Args: `{ org?: 'fss'|'fsc'|'all', query?: string, limit?: number }`
- dart_filings: OpenDART filings (needs `DART_API_KEY`); falls back to dart site news
  - Args: `{ corp_name?: string, corp_code?: string, bgn_de?: 'YYYYMMDD', end_de?: 'YYYYMMDD', page_count?: number }`
- stock_prices: Yahoo Finance chart JSON OHLCV time series
  - Args: `{ symbol: string, range?: string, interval?: string }`
- portfolio_snapshot: Weighted portfolio metrics (return/vol/drawdown)
  - Args: `{ positions: { symbol: string, weight: number }[], range?: string, interval?: string }`
- discover_market: Resolve keywords to symbols (commodities/FX/indices/equities)
  - Args: `{ category?: 'commodity'|'fx'|'index'|'equity'|'auto', keyword: string, limit?: number }`
  - Example: `discover_market { category: 'commodity', keyword: '커피' }` → `KC=F`
- analyze_keyword: One-shot: discover symbol by keyword and analyze chart trend
  - Args: `{ category?: string, keyword: string, range?: string, interval?: string }`
  - Example: `analyze_keyword { category: 'fx', keyword: '원/달러', range: '1mo' }`

## Macro/Markets
- market_quotes: Multi-asset Yahoo time series (indices/FX/commodities/futures)
  - Args: `{ symbols: string[], range?: string, interval?: string }`
  - Example symbols: `['^GSPC','^KS11','CL=F','GC=F','NG=F','KRW=X','EURUSD=X','^TNX','^VIX']`
- options_chain: Yahoo options chain
  - Args: `{ symbol: string, expiration?: 'YYYY-MM-DD' }`
- fred_series: U.S. macro via FRED (requires `FRED_API_KEY`)
  - Args: `{ series_ids: string[], start?: 'YYYY-MM-DD', end?: 'YYYY-MM-DD', frequency?: 'm'|'q'|'a', aggregation_method?: 'avg'|'sum'|'eop' }`
  - Common IDs: `DGS1,DGS2,DGS5,DGS10,DGS30` (Treasury yields), `CPIAUCSL` (CPI), `PCE`.
- bok_series: Korea macro via BOK ECOS (requires `BOK_API_KEY`)
  - Args: `{ stat_code: string, start: string, end: string, cycle?: 'M'|'Q'|'A', item_code1?: string, item_code2?: string, item_code3?: string }`
  - Use the ECOS portal to find stat/item codes.
- macro_preset: Curated macro bundles (multi-asset quotes + FRED series)
  - Args: `{ preset?: 'us_core'|'kr_core'|'global', range?: string, interval?: string, groups?: string[], fred_series?: string[], fred_start?: 'YYYY-MM-DD', fred_end?: 'YYYY-MM-DD' }`
  - Presets:
    - us_core: US equities, rates/FX, commodities, vol + FRED yields/CPI/UNRATE
    - kr_core: KOSPI/KRW + commodities/vol; FRED yields for context
    - global: US + KR + commodities/vol + FRED yields
  - Example: `macro_preset { preset: "us_core", range: "3mo", interval: "1d" }`

### KR Yield Curve via ECOS
`macro_preset` can include Korean government bond yields (ECOS) when you provide ECOS codes:

- Additional Args for `macro_preset`:
  - `include_ecos_kr_yield?: boolean`
  - `ecos_stat_code?: string` (ECOS statistic code for KR yields)
  - `ecos_cycle?: 'M'|'Q'|'A'` (default 'M')
  - `ecos_start?: string`, `ecos_end?: string` (e.g., '201801' .. '202512')
  - `ecos_items?: { label: string, item_code1: string, item_code2?: string, item_code3?: string }[]`

- Example (fill actual ECOS codes):
  ```
  macro_preset {
    preset: "kr_yield",
    range: "6mo", interval: "1d",
    include_ecos_kr_yield: true,
    ecos_stat_code: "<ECOS_STAT_CODE>",
    ecos_start: "201801", ecos_end: "202512",
    ecos_items: [
      { label: "3M",  item_code1: "<ITEM_CODE_FOR_3M>" },
      { label: "1Y",  item_code1: "<ITEM_CODE_FOR_1Y>" },
      { label: "3Y",  item_code1: "<ITEM_CODE_FOR_3Y>" },
      { label: "5Y",  item_code1: "<ITEM_CODE_FOR_5Y>" },
      { label: "10Y", item_code1: "<ITEM_CODE_FOR_10Y>" },
      { label: "20Y", item_code1: "<ITEM_CODE_FOR_20Y>" },
      { label: "30Y", item_code1: "<ITEM_CODE_FOR_30Y>" }
    ]
  }
  ```

  - Requires `BOK_API_KEY`.

## Interpretation
- analyze_markets: Compute signals and return a concise Korean narrative
  - Args: `{ range?: string, interval?: string, equities?: string[], include_vix?: boolean, rates_source?: 'fred'|'yahoo', fred_series?: string[], company_symbol?: string, company_name?: string, filings_days?: number, include_fx?: boolean, include_commodities?: boolean, fx_symbols?: string[], commodity_symbols?: string[] }`
  - Examples:
    - `analyze_markets { range: "1mo", equities: ["^GSPC","^NDX","^KS11"], include_vix: true }`
    - `analyze_markets { range: "1mo", company_symbol: "005930.KS", company_name: "삼성전자", filings_days: 14 }`
  - Notes: For FRED yields, set `FRED_API_KEY`. DART filings need `DART_API_KEY`.
- analyze_company: Company-focused interpretation (price + filings + news + regulator mentions)
  - Args: `{ company_symbol: string, company_name?: string, range?: string, interval?: string, news_limit?: number, filings_days?: number, include_regulator_news?: boolean }`
  - Example: `analyze_company { company_symbol: "005930.KS", company_name: "삼성전자", range: "1mo" }`
  - Behavior: Works without API keys; will fallback (e.g., DART -> news) and annotate warnings.

### Env vars
- `DART_API_KEY`: for OpenDART filings
- `FRED_API_KEY`: for U.S. FRED series
- `BOK_API_KEY`: for Bank of Korea ECOS series
- `COMPLIANCE_MODE`: set to `1` to tighten behavior (e.g., audit logs on; use curated feeds only)

### Audit logging
- Writes lightweight JSON lines to `logs/audit.jsonl` for core tools (inputs + result keys only).
- Disable by removing/adjusting `_audit` calls in `server.py` if your policy requires no local logs.

## Examples
- FSC press 10: `regulator_news { org: "fsc", limit: 10 }`
- Samsung Electronics filings: `dart_filings { corp_name: "삼성전자", page_count: 20 }`
- Samsung Electronics 1mo daily: `stock_prices { symbol: "005930.KS", range: "1mo", interval: "1d" }`
- summary_kr / summary_us / summary_global: One-click preset market summaries (click the button in Claude Desktop)
  - Args: `{ range?: string, interval?: string }`
- commodity_coffee / commodity_wti / commodity_gold / commodity_copper: One-click commodity analysis presets
  - Args: `{ range?: string, interval?: string }`

