from __future__ import annotations

import logging
from typing import Dict, Any, Optional, List

from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP

from .data_sources import (
    _fetch_yahoo_chart,
    _news_all,
    _yahoo_options_chain,
    _fred_fetch,
    _ecos_fetch,
    _dart_filings,
)

logger = logging.getLogger("finance-mcp")

app = FastMCP("finance-news")


class ChartArgs(BaseModel):
    symbol: str = Field(..., description="Ticker symbol")
    range: str = Field("1mo")
    interval: str = Field("1d")


@app.tool()
def fetch_chart(args: ChartArgs) -> Dict[str, Any]:
    """Fetch historical price chart for a symbol."""
    return _fetch_yahoo_chart(args.symbol, args.range, args.interval)


@app.tool()
def latest_news(limit: int = 10) -> Dict[str, Any]:
    """Return the latest news items from configured feeds."""
    items = _news_all()[:limit]
    return {"items": items}


class OptionsArgs(BaseModel):
    symbol: str = Field(..., description="Ticker symbol")
    expiration: Optional[str] = Field(None, description="Expiration date (YYYY-MM-DD)")


@app.tool()
def options_chain(args: OptionsArgs) -> Dict[str, Any]:
    """Fetch options chain data for a symbol."""
    return _yahoo_options_chain(args.symbol, args.expiration)


class FREDArgs(BaseModel):
    series_ids: List[str] = Field(..., description="List of FRED series IDs")
    start: Optional[str] = Field(None, description="Observation start date (YYYY-MM-DD)")
    end: Optional[str] = Field(None, description="Observation end date (YYYY-MM-DD)")
    frequency: Optional[str] = Field(None, description="Data frequency (e.g., m for monthly)")
    aggregation_method: Optional[str] = Field(
        None, description="Aggregation method", alias="aggregation_method"
    )


@app.tool()
def fred_series(args: FREDArgs) -> Dict[str, Any]:
    """Fetch economic data series from FRED."""
    return _fred_fetch(args)


class EcosArgs(BaseModel):
    stat_code: str = Field(..., description="ECOS statistic code (e.g., 722Y001)")
    start: str = Field(..., description="Start period (YYYYMM or YYYY) depending on cycle")
    end: str = Field(..., description="End period (YYYYMM or YYYY) depending on cycle")
    cycle: str = Field(..., description="Data cycle (e.g., D, M, Q, Y)")
    item_code1: Optional[str] = Field(None, description="First item code filter")
    item_code2: Optional[str] = Field(None, description="Second item code filter")
    item_code3: Optional[str] = Field(None, description="Third item code filter")


@app.tool()
def ecos_series(args: EcosArgs) -> Dict[str, Any]:
    """Fetch macroeconomic time series from the Bank of Korea ECOS API."""
    return _ecos_fetch(args)


class DartArgs(BaseModel):
    corp_name: Optional[str] = Field(None, description="Company name")
    corp_code: Optional[str] = Field(None, description="DART corporation code")
    bgn_de: Optional[str] = Field(None, description="Begin date (YYYYMMDD)")
    end_de: Optional[str] = Field(None, description="End date (YYYYMMDD)")
    page_count: int = Field(10, description="Number of results")


@app.tool()
def dart_filings(args: DartArgs) -> Dict[str, Any]:
    """Fetch recent filings from the Korean DART system."""
    return _dart_filings(
        corp_name=args.corp_name,
        corp_code=args.corp_code,
        bgn_de=args.bgn_de,
        end_de=args.end_de,
        page_count=args.page_count,
    )


__all__ = [
    "app",
    "fetch_chart",
    "latest_news",
    "options_chain",
    "fred_series",
    "ecos_series",
    "dart_filings",
]
