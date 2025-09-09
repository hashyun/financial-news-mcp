from __future__ import annotations

import logging
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import requests_cache  # type: ignore
except Exception:  # pragma: no cover
    requests_cache = None

logger = logging.getLogger("finance-mcp")


def _build_session() -> requests.Session:
    """Build a cached HTTP session with retry logic."""
    if requests_cache:
        try:
            requests_cache.install_cache("http_cache", expire_after=180)
            logger.info("requests-cache enabled (TTL=180s)")
        except Exception:
            pass
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.headers.update(
        {
            "User-Agent": "finnews-mcp/1.0 (+https://github.com/openai/codex-cli)",
            "Accept": "*/*",
        }
    )
    return s


SESSION = _build_session()


def _http_get(url: str, *, params: Optional[dict] = None, timeout: int = 30) -> requests.Response:
    """HTTP GET using the shared session."""
    r = SESSION.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r


__all__ = ["SESSION", "_http_get", "_build_session"]
