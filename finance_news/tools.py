from __future__ import annotations

import logging
from typing import Dict, Any, Optional

from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP

from .data_sources import _fetch_yahoo_chart, _news_all

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


__all__ = ["app", "fetch_chart", "latest_news"]
