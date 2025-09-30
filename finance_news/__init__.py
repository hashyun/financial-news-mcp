"""Finance news MCP package."""

from .network import SESSION, _http_get
from .data_sources import (
    COMMODITY_MAP,
    FX_ALIAS,
    INDEX_MAP,
    EQUITY_MAP,
    INDUSTRY_MAP,
    _fetch_yahoo_chart,
    _yahoo_options_chain,
    _google_news_rss,
    _normalize_article,
    _news_all,
    _fred_fetch,
    _ecos_fetch,
    _dart_filings,
    _get_industry_recommendations,
)
from .tools import app

__all__ = [
    "app",
    "SESSION",
    "_http_get",
    "COMMODITY_MAP",
    "FX_ALIAS",
    "INDEX_MAP",
    "EQUITY_MAP",
    "INDUSTRY_MAP",
    "_fetch_yahoo_chart",
    "_yahoo_options_chain",
    "_google_news_rss",
    "_normalize_article",
    "_news_all",
    "_fred_fetch",
    "_ecos_fetch",
    "_dart_filings",
    "_get_industry_recommendations",
]
